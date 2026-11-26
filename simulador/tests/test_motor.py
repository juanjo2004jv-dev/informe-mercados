"""Pruebas del motor con casos de solución conocida (se ejecutan en cada ejecución del workflow)."""
import numpy as np
import pandas as pd

from simulador import datos, motor


def _dia(precio, **extra):
    idx = pd.date_range(pd.Timestamp("2026-07-15", tz="Europe/Madrid").tz_convert("UTC"), periods=96, freq="15min")
    df = pd.DataFrame(index=idx)
    df["da"] = precio
    for c in ["ida1", "cont", "pm"]:
        df[c] = precio
    for c in ["ida2", "ida3"]:
        df[c] = np.nan
    for c in ["bp_sub", "bp_baj", "pe_sub", "pe_baj", "act_sub", "act_baj", "m_sub", "m_baj", "fv_nac"]:
        df[c] = 0.0
    df["banda_sub"] = df["banda_baj"] = 500.0
    for k, v in extra.items():
        df[k] = v
    return df


def _cfg(**act):
    cfg = datos.cargar_config()
    cfg["mercados"].update({"coste_ciclado_eur_mwh": 0.0, "intradiario": False, "mfrr": False})
    cfg["activo"].update({"eta_carga": 1.0, "eta_descarga": 1.0, **act})
    return cfg


def test_arbitraje_dos_precios():
    # 8 h a 0 €/MWh y 8 h a 100 €/MWh: 50 MW / 200 MWh, sin pérdidas, 1 ciclo -> 200 MWh × 100 = 20.000 €
    p = np.r_[np.zeros(32), np.full(32, 100.0), np.full(32, 50.0)]
    cfg = _cfg(ciclos_max_dia=1.0)
    res, det = motor.simular(_dia(p), cfg["activo"], cfg)
    assert abs(res["diario_bess"].iloc[0] - 20000) < 1e-3


def test_limites_fisicos():
    rng = np.random.default_rng(0)
    p = 60 + 40 * np.sin(np.arange(96) / 96 * 4 * np.pi) + rng.normal(0, 5, 96)
    cfg = _cfg(eta_carga=0.938, eta_descarga=0.938)
    df = _dia(p, bp_sub=8.0, bp_baj=6.0, act_sub=50.0, act_baj=50.0)
    res, det = motor.simular(df, cfg["activo"], cfg)
    a = cfg["activo"]
    assert (det["e"] <= a["e_bess_mwh"] + 1e-6).all() and (det["e"] >= -1e-6).all()
    assert (det["dis"] + det["bu"] <= a["p_bess_mw"] + 1e-6).all()
    assert (det["cg"] + det["bd"] <= a["p_bess_mw"] + 1e-6).all()
    assert res["ciclos"].iloc[0] <= a["ciclos_max_dia"] + 1e-6


def test_sin_carga_de_red():
    p = np.r_[np.zeros(32), np.full(64, 100.0)]
    cfg = _cfg(carga_desde_red=False, p_poi_import_mw=0, fv_mwp=0)
    res, det = motor.simular(_dia(p), cfg["activo"], cfg)
    assert det["cg"].abs().max() < 1e-9 and abs(res["diario_bess"].iloc[0]) < 1e-6


def test_precio_negativo_no_carga_y_descarga_a_la_vez():
    p = np.r_[np.full(48, -20.0), np.full(48, 80.0)]
    cfg = _cfg(eta_carga=0.9, eta_descarga=0.9)
    res, det = motor.simular(_dia(p), cfg["activo"], cfg)
    assert ((det["cg"] > 1e-6) & (det["dis"] > 1e-6)).sum() == 0


def test_banda_secuencial_no_supera_cooptimizada():
    # El orden real (diario y después banda) nunca puede ganar más que decidir ambos a la vez con la misma
    # información: la co-optimización es la cota superior. El diario del secuencial es el óptimo solo-diario.
    rng = np.random.default_rng(1)
    p = 70 + 50 * np.sin(np.arange(96) / 96 * 4 * np.pi) + rng.normal(0, 5, 96)
    df = _dia(p, bp_sub=12.0, bp_baj=5.0)
    cfg = _cfg(eta_carga=0.938, eta_descarga=0.938)
    cfg["mercados"]["afrr_activacion"] = False
    r_co, _ = motor.simular(df, cfg["activo"], cfg)
    cfg_s = _cfg(eta_carga=0.938, eta_descarga=0.938)
    cfg_s["mercados"].update({"afrr_activacion": False, "banda_secuencial": True})
    r_se, _ = motor.simular(df, cfg_s["activo"], cfg_s)
    cfg_d = _cfg(eta_carga=0.938, eta_descarga=0.938)
    cfg_d["mercados"].update({"afrr_activacion": False, "afrr_banda": False})
    r_da, _ = motor.simular(df, cfg_d["activo"], cfg_d)
    tot = lambda r: float(r["diario_bess"].iloc[0] + r["afrr_banda"].iloc[0])  # noqa: E731
    assert tot(r_se) <= tot(r_co) + 1e-6
    assert abs(r_se["diario_bess"].iloc[0] - r_da["diario_bess"].iloc[0]) < 1e-6
    assert r_se["afrr_banda"].iloc[0] > 0


def test_prevision_no_usa_el_propio_dia():
    # La previsión de un día solo puede usar días anteriores: el día 3 se prevé con la media de 1 y 2.
    from simulador import pronostico
    idx = pd.date_range(pd.Timestamp("2026-07-13", tz="Europe/Madrid").tz_convert("UTC"), periods=96 * 3, freq="15min")
    s = pd.Series(np.r_[np.full(96, 10.0), np.full(96, 30.0), np.full(96, 1000.0)], index=idx)
    p = pronostico.prevision(s, dias=7, metodo="media")
    assert np.allclose(p.iloc[192:].values, 20.0)
    assert np.allclose(p.iloc[96:192].values, 10.0)


def test_previsión_imperfecta_cobra_precio_real():
    # Si la previsión es plana no hay señal para arbitrar: el diario no puede ganar dinero «por suerte».
    p = np.r_[np.zeros(32), np.full(32, 100.0), np.full(32, 50.0)]
    df = _dia(p)
    cfg = _cfg(ciclos_max_dia=1.0)
    cfg["prevision"] = {"modo": "imperfecta"}
    d = motor.preparar(df, cfg["activo"], cfg)
    d["da_prev"] = 50.0
    d["bp_sub_prev"] = d["bp_baj_prev"] = 0.0
    for k in ("ida1", "ida2", "ida3"):
        d[f"{k}_dif_prev"] = 0.0
    lin, met, det = motor.simular_dia(d, cfg["activo"], cfg)
    assert abs(lin["diario_bess"]) < 1e-6


def test_tiempo_real_respeta_soc_y_cierre_del_continuo():
    # Programa vacío: una activación a subir solo se entrega si hay energía, y su reposición no puede
    # empezar antes de 1 h + 1 cuarto (cierre del continuo 60 min antes de la entrega).
    p = np.full(96, 50.0)
    df = _dia(p)
    cfg = _cfg()
    a = cfg["activo"]
    d = motor.preparar(df, a, cfg)
    T = len(d)
    s2 = {k: np.zeros(T) for k in ("cg", "cpv", "dis", "pvx")}
    z = np.zeros(T)
    aU = z.copy(); aU[10] = 20.0
    for e0, esperado in ((0.0, 0.0), (100.0, 20.0)):
        s2["e"] = np.full(T, e0)
        eu, edn, ing, no = motor._tiempo_real(d, a, cfg["mercados"], s2, z, z, aU, z, z, z, 1.0, 1.0, e0)
        assert abs(eu[10] - esperado) < 1e-9
    # con energía: la recompra (coste) existe y la energía repuesta cuadra con la activada
    assert ing < 0


def test_perfil_fv_emplazamiento_cuadra_energia_mensual(monkeypatch):
    # La energía del mes es la de PVGIS (proporcional a los días) y la forma, la de la FV peninsular.
    from simulador import datos
    monkeypatch.setattr(datos, "pvgis_mensual", lambda *a, **k: {m: 200.0 for m in range(1, 13)})
    idx = pd.date_range(pd.Timestamp("2026-07-01", tz="Europe/Madrid").tz_convert("UTC"), periods=96 * 3, freq="15min")
    hora = idx.tz_convert("Europe/Madrid").hour
    df = pd.DataFrame({"fv_nac": np.where((hora >= 8) & (hora < 20), 1000.0, 0.0)}, index=idx)
    fv = datos.perfil_fv(df, 50, 1.0, {"lat": 38.88, "lon": -6.97})
    assert abs(fv.sum() * 0.25 - 200 * 50 * 3 / 31) < 1e-3   # kWh/kWp = MWh/MWp
    assert fv.max() <= 50


def test_pvgis_mensual_elige_montaje(tmp_path, monkeypatch):
    # PVGIS con inclined_axis devuelve también "fixed": seguidor=True debe leer inclined_axis.
    import json
    from simulador import datos
    monkeypatch.setattr(datos, "PVGIS", tmp_path)
    j = {"outputs": {"monthly": {"fixed": [{"month": m, "E_m": 100.0} for m in range(1, 13)],
                                 "inclined_axis": [{"month": m, "E_m": 150.0} for m in range(1, 13)]}}}
    (tmp_path / "1.000_2.000_seguidor_14.json").write_text(json.dumps(j))
    (tmp_path / "1.000_2.000_fijo_14.json").write_text(json.dumps(j))
    assert datos.pvgis_mensual(1, 2, True, 14)[7] == 150.0
    assert datos.pvgis_mensual(1, 2, False, 14)[7] == 100.0


def test_finanzas_tir_y_degradacion():
    from simulador import finanzas
    # TIR conocida: −100 y +110 a un año = 10 %
    assert abs(finanzas.tir([-100, 110]) - 0.10) < 1e-6
    fz = {"vida_anos": 15, "inflacion": 0.0, "capex": {"potencia_eur_kw": 152, "energia_eur_kwh": 98.75},
          "opex_fijo_eur_kw_ano": 15, "wacc": 0.109, "impuesto_sociedades": 0.25, "ivpee": 0.0,
          "peaje_generacion_eur_mwh": 0.0, "degradacion": {"calendario_pct_ano": 1.0, "ciclo_pct_por_1000_efc": 3.0},
          "trayectorias": {"plana": {"tipo": "plana"}}}
    anual = {"diario_bess": 100000.0, "afrr_banda": 50000.0, "ciclos_dia": 1.0, "apuntamiento": 100.0}
    capex, f = finanzas.proyectar(anual, 4, fz, "plana")
    assert capex == 547000.0
    # SOH: 1 %/año + 3 % × 365/1000 = 2,095 %/año; año 1 a mitad de periodo
    assert abs(f["soh"].iloc[0] - (1 - 0.02095 / 2)) < 1e-9
    # la banda (potencia) no se degrada; el diario sí
    assert abs(f["ingreso"].iloc[0] - (100000 * f["soh"].iloc[0] + 50000)) < 1e-6
    m = finanzas.metricas(capex, f, fz)
    assert m["tir_despues"] < m["tir_antes"] and m["lcos"] > 0


def test_precio_gdo_por_mes():
    import pandas as pd
    from simulador import motor
    g = {"desde": "2026-01", "precios": {"2026-01": 1.65, "2026-09": 1.58}}
    ts = lambda s: pd.Timestamp(s, tz="Europe/Madrid").tz_convert("UTC")  # noqa: E731
    assert motor.precio_gdo(ts("2025-12-15"), g) == 0.0          # antes de «desde»: sin GdO
    assert motor.precio_gdo(ts("2026-01-01 00:00"), g) == 1.65   # mes local (no UTC)
    assert motor.precio_gdo(ts("2026-05-10"), g) == 1.65         # sin precio del mes: último anterior conocido
    assert motor.precio_gdo(ts("2026-11-10"), g) == 1.58
