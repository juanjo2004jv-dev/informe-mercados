"""Motor de despacho BESS (y FV + BESS) por optimización lineal entera mixta (HiGHS vía SciPy).

Secuencia por día (hora local, 92-100 cuartos):
  Etapa 1 · Diario: diario + banda aFRR, previsión perfecta del día (como Modo, ME vBESS ES v0.5).
  Etapa 2 · Intradiario: IDA1, IDA2 e IDA3 reoptimizan por turno los cuartos que cubren, banda fijada.
  Etapa 3 · Tiempo real: activaciones aFRR (banda × ratio activada/asignada del sistema), mFRR con la
            potencia libre y tope de profundidad de mercado, y reposición del SoC en el continuo al precio
            medio de las horas siguientes.
Todas las reglas que no están verificadas se marcan SUPUESTO en config.yml y en el informe.
"""
import math

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

DT = 0.25  # horas por cuarto


def p_eff(P, D, umbral):
    """Potencia efectiva (Modo, §5.6.1): lineal hasta el umbral T = umbral·D, logarítmica después."""
    T = umbral * D
    return P if P <= T else T * (1 + math.log(P / T))


class _LP:
    """Constructor mínimo de problemas lineales con variables vectoriales."""

    def __init__(self):
        self.n = 0
        self.lb, self.ub, self.integ, self.c = [], [], [], []
        self.rows, self.cols, self.vals, self.rlo, self.rhi = [], [], [], [], []
        self.nr = 0

    def var(self, T, lb=0.0, ub=np.inf, entero=False):
        idx = np.arange(self.n, self.n + T)
        self.n += T
        self.lb += list(np.broadcast_to(lb, T))
        self.ub += list(np.broadcast_to(ub, T))
        self.integ += [1 if entero else 0] * T
        self.c += [0.0] * T
        return idx

    def obj(self, idx, coef):
        for i, v in zip(idx, np.broadcast_to(coef, len(idx))):
            self.c[i] += v

    def fila(self, terminos, lo=-np.inf, hi=np.inf):
        """terminos: lista de (indice_variable, coeficiente)."""
        for i, v in terminos:
            self.rows.append(self.nr)
            self.cols.append(int(i))
            self.vals.append(float(v))
        self.rlo.append(lo)
        self.rhi.append(hi)
        self.nr += 1

    def resolver(self):
        A = coo_matrix((self.vals, (self.rows, self.cols)), shape=(self.nr, self.n))
        r = milp(c=-np.array(self.c), integrality=np.array(self.integ),
                 bounds=Bounds(np.array(self.lb), np.array(self.ub)),
                 constraints=LinearConstraint(A.tocsr(), np.array(self.rlo), np.array(self.rhi)),
                 options={"disp": False, "mip_rel_gap": 1e-6, "time_limit": 60})
        if r.x is None:
            raise RuntimeError(f"Optimización sin solución: {r.message}")
        return r.x


def _despacho(d, a, m, precio, bu_fijo=None, bd_fijo=None, fijo=None, e0=None):
    """Resuelve el programa físico de un día. Si bu_fijo/bd_fijo vienen dados, la banda está fijada
    (etapa 2). `precio` es el precio de la energía usado en el objetivo. `fijo` = (máscara, programa
    previo): en los cuartos de la máscara el programa no se puede cambiar (intradiario que no cubre esas
    horas). `e0` = SoC inicial en MWh (si no, soc_inicial × E)."""
    T = len(d)
    P, E = a["p_bess_mw"], a["e_bess_mwh"]
    POI, PIMP = a["p_poi_mw"], (a["p_poi_import_mw"] if a["carga_desde_red"] else 0.0)
    ec, ed = a["eta_carga"], a["eta_descarga"]
    S = d["fv"].values
    kappa = m["coste_ciclado_eur_mwh"]
    iv = m.get("ivpee", 0.0)
    lp = _LP()
    def _caja(nombre, ub):
        lb_, ub_ = np.zeros(T), np.broadcast_to(np.asarray(ub, float), T).copy()
        if fijo is not None:
            msk, prev = fijo
            lb_[msk] = prev[nombre][msk]
            ub_[msk] = prev[nombre][msk]
        return lb_, ub_
    cg = lp.var(T, *_caja("cg", PIMP))
    cpv = lp.var(T, *_caja("cpv", P))
    dis = lp.var(T, *_caja("dis", P))
    pvx = lp.var(T, *_caja("pvx", S))
    e = lp.var(T, 0, E)
    con_banda = m["afrr_banda"] and bu_fijo is None
    if bu_fijo is None:
        bu = lp.var(T, 0, d["cap_bu"].values if m["afrr_banda"] else 0)
        bd = lp.var(T, 0, d["cap_bd"].values if m["afrr_banda"] else 0)
    else:
        bu = lp.var(T, bu_fijo, bu_fijo)
        bd = lp.var(T, bd_fijo, bd_fijo)
    rg = lp.var(T, 0, PIMP)
    binarios = bool((precio < 0).any())
    u = lp.var(T, 0, 1, entero=True) if binarios else None

    venta = np.where(precio > 0, precio * (1 - iv), precio)
    lp.obj(pvx, venta * DT)
    lp.obj(dis, venta * DT - kappa * DT)
    lp.obj(cg, -precio * DT)
    if con_banda:
        lp.obj(bu, d["bp_sub"].values * DT)
        lp.obj(bd, d["bp_baj"].values * DT)

    e0 = a["soc_inicial"] * E if e0 is None else e0
    tau = m["tau_afrr_h"]
    for t in range(T):
        lp.fila([(cpv[t], 1), (pvx[t], 1)], hi=S[t])                       # reparto FV
        lp.fila([(cg[t], 1), (cpv[t], 1), (bd[t], 1)], hi=P)               # potencia de carga + banda bajar
        lp.fila([(dis[t], 1), (bu[t], 1)], hi=P)                           # potencia de descarga + banda subir
        lp.fila([(pvx[t], 1), (dis[t], 1), (bu[t], 1)], hi=POI)            # inyección en el POI
        lp.fila([(cg[t], 1), (rg[t], 1)], hi=PIMP)                         # consumo desde red
        lp.fila([(rg[t], 1), (cg[t], 1), (cpv[t], 1)], hi=P)               # margen de carga extra
        lp.fila([(bd[t], 1), (pvx[t], -1), (dis[t], -1), (rg[t], -1)], hi=0)  # de dónde sale la banda a bajar
        prev_e = [(e[t - 1], -1)] if t else []
        lp.fila([(e[t], 1)] + prev_e + [(cg[t], -ec * DT), (cpv[t], -ec * DT), (dis[t], DT / ed)],
                lo=e0 if t == 0 else 0, hi=e0 if t == 0 else 0)            # balance de SoC
        lp.fila([(e[t], 1), (bu[t], -tau / ed)], lo=0)                     # SoC para cubrir subir (fin)
        lp.fila([(e[t], 1), (bd[t], tau * ec)], hi=E)                      # hueco para cubrir bajar (fin)
        if t:                                                              # y al inicio del cuarto
            lp.fila([(e[t - 1], 1), (bu[t], -tau / ed)], lo=0)
            lp.fila([(e[t - 1], 1), (bd[t], tau * ec)], hi=E)
        else:
            lp.fila([(bu[t], tau / ed)], hi=e0)
            lp.fila([(bd[t], tau * ec)], hi=E - e0)
        if binarios:
            lp.fila([(cg[t], 1), (cpv[t], 1), (u[t], -P)], hi=0)
            lp.fila([(dis[t], 1), (u[t], P)], hi=P)
    # ciclos: descarga DC por arbitraje + activación esperada de la banda a subir
    ar = d["ratio_sub"].values
    lp.fila([(dis[t], DT / ed) for t in range(T)] + [(bu[t], ar[t] * DT / ed) for t in range(T)],
            hi=a["ciclos_max_dia"] * E)
    # la banda se asigna por hora: igual en los cuartos de cada hora
    horaria = m.get("banda_horaria", "auto")
    if horaria == "auto":   # horaria solo si el precio de banda publicado no cambia dentro de la hora
        hh = d.index.floor("h")
        horaria = bool((d["bp_sub"].groupby(hh).nunique() <= 1).all() and (d["bp_baj"].groupby(hh).nunique() <= 1).all())
    if con_banda and horaria:
        hora = d.index.tz_convert("Europe/Madrid").floor("h")
        for _, pos in pd.Series(range(T), index=hora).groupby(level=0):
            p0 = pos.values
            for p in p0[1:]:
                lp.fila([(bu[p], 1), (bu[p0[0]], -1)], lo=0, hi=0)
                lp.fila([(bd[p], 1), (bd[p0[0]], -1)], lo=0, hi=0)
    x = lp.resolver()
    g = lambda ix: x[ix]  # noqa: E731
    return {"cg": g(cg), "cpv": g(cpv), "dis": g(dis), "pvx": g(pvx), "e": g(e), "bu": g(bu), "bd": g(bd)}


def preparar(df, a, cfg):
    """Añade al DataFrame del periodo las columnas derivadas: FV, ratios de activación y topes."""
    from .datos import perfil_fv
    d = df.copy()
    d["fv"] = perfil_fv(d, a.get("fv_mwp", 0), a.get("fv_ratio_dc_ac", 1.0)).values
    d["ratio_sub"] = (d["act_sub"] / d["banda_sub"].where(d["banda_sub"] > 0)).clip(0, 1).fillna(0)
    d["ratio_baj"] = (d["act_baj"] / d["banda_baj"].where(d["banda_baj"] > 0)).clip(0, 1).fillna(0)
    P = a["p_bess_mw"]
    pr = cfg["profundidad"]
    fb, fm = pr["afrr_banda"], pr["mfrr"]
    if fb.get("activa", True):
        pe_u, pe_d = p_eff(P, fb["D_sub"], fb["umbral"]), p_eff(P, fb["D_baj"], fb["umbral"])
        d["cap_bu"] = np.minimum(pe_u * d["banda_sub"].fillna(0) / fb["D_sub"], fb["techo"] * P)
        d["cap_bd"] = np.minimum(pe_d * d["banda_baj"].fillna(0) / fb["D_baj"], fb["techo"] * P)
    else:  # precio-aceptante: solo limita la banda total asignada al sistema
        d["cap_bu"] = np.minimum(d["banda_sub"].fillna(0), P)
        d["cap_bd"] = np.minimum(d["banda_baj"].fillna(0), P)
    if fm.get("activa", True):
        pm_u, pm_d = p_eff(P, fm["D_sub"], fm["umbral"]), p_eff(P, fm["D_baj"], fm["umbral"])
        d["cap_mu"] = np.minimum(pm_u * d["m_sub"].abs() / fm["D_sub"], fm["techo"] * P)
        d["cap_md"] = np.minimum(pm_d * d["m_baj"].abs() / fm["D_baj"], fm["techo"] * P)
    else:
        d["cap_mu"] = np.minimum(d["m_sub"].abs(), P)
        d["cap_md"] = np.minimum(d["m_baj"].abs(), P)
    # Precio de reposición del SoC: media del continuo en las próximas h horas (la energía activada se
    # recompra o revende después, no en el mismo cuarto). Al final del periodo, el propio cuarto.
    n = max(int(round(cfg["mercados"].get("reposicion_horizonte_h", 2) / DT)), 1)
    fut = d["cont"][::-1].rolling(n, min_periods=1).mean()[::-1].shift(-1)
    d["p_rep"] = fut.fillna(d["cont"])
    d["p_id"] = d["ida1"].fillna(d["ida2"]).fillna(d["ida3"]).fillna(d["da"])
    return d


def simular_dia(d, a, cfg, e0=None):
    m = cfg["mercados"]
    ec, ed = a["eta_carga"], a["eta_descarga"]
    rt = ec * ed
    kappa = m["coste_ciclado_eur_mwh"]
    pda = d["da"].values
    s1 = _despacho(d, a, m, pda, e0=e0)
    # Etapa 2: cada subasta intradiaria reoptimiza solo los cuartos que cubre (IDA1 y IDA2 todo el día,
    # IDA3 desde las 12:00), con la banda fijada y lo anterior como punto de partida.
    s2, ingreso_id = s1, 0.0
    if m.get("intradiario", True):
        for k in ("ida1", "ida2", "ida3"):
            p = d[k].values
            cubre = ~np.isnan(p)
            if not cubre.any():
                continue
            nuevo = _despacho(d, a, m, np.where(cubre, p, 0.0), bu_fijo=s1["bu"], bd_fijo=s1["bd"],
                              fijo=(~cubre, s2), e0=e0)
            dn = (nuevo["pvx"] + nuevo["dis"] - nuevo["cg"]) - (s2["pvx"] + s2["dis"] - s2["cg"])
            ingreso_id += float(np.nansum(np.where(cubre, p, 0.0) * dn) * DT)
            s2 = nuevo
    P, POI = a["p_bess_mw"], a["p_poi_mw"]
    PIMP = a["p_poi_import_mw"] if a["carga_desde_red"] else 0.0
    bu, bd = s1["bu"], s1["bd"]
    # etapa 3 · activaciones
    aU = bu * d["ratio_sub"].values if m["afrr_activacion"] else 0 * bu
    aD = bd * d["ratio_baj"].values if m["afrr_activacion"] else 0 * bd
    pc = d["p_rep"].values
    pm = d["pm"].fillna(d["cont"]).values
    if m["mfrr"]:
        h_up = np.maximum(0, np.minimum(P - s2["dis"] - bu, POI - s2["pvx"] - s2["dis"] - bu))
        dn_red = (PIMP - s2["cg"] - bd) if a["carga_desde_red"] else (s2["pvx"] + s2["dis"] - bd)
        h_dn = np.maximum(0, np.minimum(P - s2["cg"] - s2["cpv"] - bd, dn_red))
        mU = np.where(pm > pc / rt + kappa, np.minimum(h_up, d["cap_mu"].values), 0.0)
        mD = np.where(pm < pc * rt - kappa, np.minimum(h_dn, d["cap_md"].values), 0.0)
        # El precio 2197 es el de la dirección dominante del cuarto (verificado: con bajada dominante va
        # 44 €/MWh por debajo del continuo; con subida, casi igual). Solo se participa en esa dirección.
        sub_dom = d["m_sub"].abs().values >= d["m_baj"].abs().values
        mU = np.where(sub_dom & (d["m_sub"].abs().values > 0), mU, 0.0)
        mD = np.where(~sub_dom & (d["m_baj"].abs().values > 0), mD, 0.0)
    else:
        mU = mD = 0 * bu
    lineas = {
        "diario_bess": float(np.sum(pda * (s1["dis"] - s1["cg"])) * DT),
        "diario_fv": float(np.sum(pda * s1["pvx"]) * DT),
        "intradiario": ingreso_id,
        "afrr_banda": float(np.sum(d["bp_sub"].values * bu + d["bp_baj"].values * bd) * DT),
        "afrr_activacion": float(np.sum(d["pe_sub"].values * aU - d["pe_baj"].values * aD) * DT),
        "mfrr": float(np.sum(pm * (mU - mD)) * DT),
        "reposicion": float(np.sum(pc * ((aD + mD) * rt - (aU + mU) / rt)) * DT),
    }
    descarga = float(np.sum(s2["dis"]) * DT + np.sum(aU + mU) * DT)
    lineas["coste_ciclado"] = -kappa * descarga
    iv = m.get("ivpee", 0.0)
    if iv:
        ventas = np.sum(np.maximum(pda, 0) * (s1["dis"] + s1["pvx"])) * DT
        lineas["ivpee"] = -iv * float(ventas)
    E = a["e_bess_mwh"]
    met = {
        "mwh_descarga": descarga,
        "ciclos": descarga / ed / E if E else 0.0,
        "mwh_fv": float(np.sum(d["fv"].values) * DT),
        "mwh_fv_vertida": float(np.sum(d["fv"].values - s1["pvx"] - s1["cpv"]) * DT),
        "ingreso_descarga": float(np.sum(pda * s2["dis"]) * DT),
        "banda_media_sub": float(np.mean(bu)), "banda_media_baj": float(np.mean(bd)),
    }
    detalle = pd.DataFrame({k: v for k, v in s2.items()}, index=d.index)
    detalle["bu"], detalle["bd"], detalle["aU"], detalle["aD"], detalle["mU"], detalle["mD"] = bu, bd, aU, aD, mU, mD
    met["soc_final"] = float(s2["e"][-1])
    return lineas, met, detalle


def simular(df, a, cfg, progreso=None):
    """Simula todos los días del DataFrame. Devuelve (resultados diarios, detalle por cuarto)."""
    d = preparar(df, a, cfg)
    dias = d.index.tz_convert("Europe/Madrid").normalize()
    filas, detalles = [], []
    e0 = None
    for dia, sub in d.groupby(dias):
        lin, met, det = simular_dia(sub, a, cfg, e0=e0)
        if a.get("soc_continuo", False):   # el SoC pasa de un día al siguiente
            e0 = min(max(met["soc_final"], 0.0), a["e_bess_mwh"])
        filas.append({"dia": dia.date(), **lin, **met})
        detalles.append(det)
        if progreso:
            progreso(dia)
    res = pd.DataFrame(filas).set_index("dia")
    return res, pd.concat(detalles)
