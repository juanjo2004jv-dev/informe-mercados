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
