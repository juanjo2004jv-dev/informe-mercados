"""Rentabilidad de los escenarios stand-alone: TIR, VAN, LCOS y plazo de recuperación. Determinista, sin IA.

Parte del ingreso simulado en los últimos 12 meses completos (€/MW de BESS) y lo proyecta durante la vida útil con:
  - trayectoria de mercado (finanzas.trayectorias en config.yml): base = converge a la previsión de Modo para 2028
    y se mantiene plana en términos reales; persistencia = se repite el último año; saturación = cae cada año;
  - degradación (calendario + ciclos equivalentes): las líneas que dependen de la energía (diario, intradiario,
    continuo, reposición) escalan con el SOH; las de potencia (banda aFRR, activaciones, mFRR) no, porque la banda
    solo exige 15 min de energía (P.O. 7.2) y un 4 h la cubre aunque haya perdido un 30 % (SUPUESTO);
  - costes: CAPEX (potencia + energía), O&M fijo, peaje de generación por MWh vertido, IVPEE sobre las ventas
    de la descarga e impuesto de sociedades con amortización lineal.
Todo en euros nominales; los parámetros y sus fuentes están en config.yml (finanzas).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .datos import cargar_config, tramos

RAIZ = Path(__file__).resolve().parent.parent
RES = RAIZ / "data" / "simulador" / "resultados"
ESC = Path(__file__).resolve().parent / "escenarios"
ENERGIA = ["diario_bess", "intradiario", "continuo", "reposicion"]
POTENCIA = ["afrr_banda", "afrr_activacion", "mfrr"]


def tir(flujos):
    """TIR por bisección (flujos anuales, el primero en t=0). None si no cambia de signo."""
    f = np.asarray(flujos, float)
    van = lambda r: float(np.sum(f / (1 + r) ** np.arange(len(f))))  # noqa: E731
    lo, hi = -0.99, 5.0
    if van(lo) * van(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if van(lo) * van(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _fusion(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _fusion(out.get(k, {}), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def proyectar(anual, horas, fz, trayectoria):
    """Flujos de caja anuales (€/MW de BESS) de un activo de `horas` h. `anual`: dict con las líneas de ingreso
    del año base (€/MW·año), 'ciclos_dia' y 'apuntamiento' (precio medio de descarga, €/MWh)."""
    vida = int(fz["vida_anos"])
    infl = fz["inflacion"]
    capex = (fz["capex"]["potencia_eur_kw"] + fz["capex"]["energia_eur_kwh"] * horas
             + fz.get("adquisicion_rtb_eur_kw", 0.0)) * 1000.0
    opex0 = fz["opex_fijo_eur_kw_ano"] * 1000.0
    d = fz["degradacion"]
    tr = fz["trayectorias"][trayectoria]
    r_e = sum(anual.get(k, 0.0) for k in ENERGIA)
    r_p = sum(anual.get(k, 0.0) for k in POTENCIA)
    r0 = r_e + r_p
    efc_ano = anual["ciclos_dia"] * 365.0
    filas, soh = [], 1.0
    for t in range(1, vida + 1):
        # factor de mercado (real) sobre el ingreso del año base
        if tr["tipo"] == "converge":
            obj = fz["factor_objetivo"]                       # mismo factor de mercado para todos los escenarios
            n = max(int(tr["anos"]), 1)
            fm = 1 + (obj - 1) * min(t - 1, n) / n
            fm *= (1 + tr.get("deriva_pct_ano", 0.0)) ** max(t - 1 - n, 0)   # deriva real a partir de la convergencia
        elif tr["tipo"] == "deriva":
            fm = (1 + tr["pct_ano"]) ** (t - 1)
        else:
            fm = 1.0
        soh_ini = soh
        soh = max(soh - d["calendario_pct_ano"] / 100 - d["ciclo_pct_por_1000_efc"] / 100 * efc_ano / 1000, 0.0)
        soh_med = (soh_ini + soh) / 2
        esc = (1 + infl) ** (t - 1)
        ing = (r_e * soh_med + r_p) * fm * esc
        mwh = efc_ano * horas * soh_med                      # MWh vertidos por MW de BESS
        ventas = mwh * anual["apuntamiento"] * fm * esc       # ventas de la descarga (base del IVPEE)
        ivpee = fz["ivpee"] * ventas
        peaje = fz["peaje_generacion_eur_mwh"] * mwh
        opex = opex0 * esc
        ebitda = ing - opex - ivpee - peaje
        amort = capex / vida
        imp = max(ebitda - amort, 0.0) * fz["impuesto_sociedades"]
        filas.append(dict(ano=t, soh=soh_med, factor_mercado=fm, ingreso=ing, opex=-opex, ivpee=-ivpee,
                          peaje=-peaje, ebitda=ebitda, impuesto=-imp, flujo_antes=ebitda, flujo_despues=ebitda - imp,
                          mwh=mwh))
    return capex, pd.DataFrame(filas)


def metricas(capex, f, fz):
    w = fz["wacc"]
    t = f["ano"].values
    desc = (1 + w) ** t
    fa = [-capex] + list(f["flujo_antes"])
    fd = [-capex] + list(f["flujo_despues"])
    acum = np.cumsum(fd)
    pay = next((i for i, v in enumerate(acum) if v >= 0), None)
    costes = capex + float(np.sum(-(f["opex"] + f["peaje"]) / desc))
    lcos = costes / float(np.sum(f["mwh"] / desc))
    return dict(capex=capex, tir_antes=tir(fa), tir_despues=tir(fd),
                van=-capex + float(np.sum(f["flujo_antes"] / desc)), lcos=lcos, payback=pay,
                soh_final=float(f["soh"].iloc[-1]))


def _anual(esc):
    arch = tramos(RES / esc)
    if not arch:
        return None, None
    m = pd.concat(pd.read_csv(x, index_col=0) for x in arch)
    m = m[~m.index.duplicated(keep="last")].sort_index()
    m = m[m["dias"] >= pd.PeriodIndex(m.index, freq="M").days_in_month]   # solo meses completos
    if len(m) < 12:
        return None, None
    u = m.iloc[-12:]
    anual = {k: float(u[k].sum()) for k in ENERGIA + POTENCIA + ["total", "coste_ciclado", "diario_fv"] if k in u}
    pesos = u["ciclos_dia"] * u["dias"]
    anual["ciclos_dia"] = float((u["ciclos_dia"] * u["dias"]).sum() / u["dias"].sum())
    anual["apuntamiento"] = float((u["apuntamiento"] * pesos).sum() / pesos.sum()) if pesos.sum() else 0.0
    return anual, f"{u.index[0]} a {u.index[-1]}"


def sensibilidad(ref, fz0):
    """TIR antes de impuestos del escenario de referencia (trayectoria base) al mover un parámetro cada vez."""
    e, a, anual, _ = ref
    horas = a["e_bess_mwh"] / a["p_bess_mw"]
    casos = [("Caso base", {})]
    for x in (0.75, 1.25):
        casos.append((f"CAPEX ×{x:g}".replace(".", ","), {"capex": {k: v * x for k, v in fz0["capex"].items()}}))
    casos += [("O&M ×2 (30 €/kW·año)", {"opex_fijo_eur_kw_ano": fz0["opex_fijo_eur_kw_ano"] * 2}),
              ("Sin IVPEE", {"ivpee": 0.0}),
              ("Degradación ×1,5", {"degradacion": {k: v * 1.5 for k, v in fz0["degradacion"].items()}}),
              ("Compra del RtB 100 €/kW", {"adquisicion_rtb_eur_kw": 100.0}),
              ("Ingresos de 2028 +12 % (Modo, oct-2026)",
               {"factor_objetivo": fz0["factor_objetivo"] * 1.12})]
    filas = []
    for nombre, cambio in casos:
        fz = _fusion(fz0, cambio)
        capex, fl = proyectar(anual, horas, fz, "base")
        mt = metricas(capex, fl, fz)
        filas.append(dict(caso=nombre, tir_antes=mt["tir_antes"], tir_despues=mt["tir_despues"], van=mt["van"],
                          lcos=mt["lcos"]))
    return pd.DataFrame(filas)


def calcular():
    cfg = cargar_config()
    filas, flujos = [], {}
    base = {}
    for f in sorted(ESC.glob("*.yml")):
        e = yaml.safe_load(open(f, encoding="utf-8"))
        a = _fusion(cfg["activo"], e.get("activo"))
        if a.get("fv_mwp", 0) or not e.get("finanzas", {}).get("evaluar", True):
            continue                                          # híbridos: el ingreso por MW de POI mezcla la FV
        anual, periodo = _anual(f.stem)
        if anual is None:
            continue
        base[f.stem] = (e, a, anual, periodo)
    fz0 = cfg["finanzas"]
    # La previsión de Modo (4 h stand-alone, SUPUESTO sobre la duración) se traduce en un factor de mercado
    # frente al escenario de referencia (4 h operable, últimos 12 meses), y ese factor se aplica a todos: se
    # conservan las diferencias entre duraciones y entre formas de operar que mide el simulador.
    ref = base.get(fz0["referencia_4h"])
    obj = fz0["trayectorias"]["base"]["objetivo_eur_mw_ano"]
    fz0["factor_objetivo"] = obj / ref[2]["total"] if ref else 1.0
    for k, (e, a, anual, periodo) in base.items():
        fz = _fusion(fz0, e.get("finanzas"))
        horas = a["e_bess_mwh"] / a["p_bess_mw"]
        for tr in fz["trayectorias"]:
            capex, fl = proyectar(anual, horas, fz, tr)
            mt = metricas(capex, fl, fz)
            filas.append(dict(escenario=k, nombre=e.get("nombre", k), horas=horas, trayectoria=tr,
                              periodo_base=periodo, ingreso_base=anual["total"], ciclos_dia=anual["ciclos_dia"], **mt))
            if tr == "base":
                flujos[k] = fl
    t = pd.DataFrame(filas)
    if ref:
        sensibilidad(ref, fz0).to_csv(RES / "finanzas_sensibilidad.csv", index=False)
    RES.mkdir(parents=True, exist_ok=True)
    t.to_csv(RES / "finanzas.csv", index=False)
    for k, fl in flujos.items():
        fl.round(1).to_csv(RES / k / "flujos_base.csv", index=False)
    (RES / "finanzas_supuestos.json").write_text(json.dumps({k: v for k, v in fz0.items()}, ensure_ascii=False,
                                                            indent=1, default=str), encoding="utf-8")
    return t


if __name__ == "__main__":
    print(calcular().to_string())
