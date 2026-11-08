"""Cálculo de métricas. Todo es determinista: aquí no interviene ninguna IA."""
from datetime import timedelta

import numpy as np
import pandas as pd

TZ = "Europe/Madrid"


# ---------------------------------------------------------------- tiempo
def rejilla(inicio, fin):
    """Cuartos de hora [inicio, fin) en UTC (respeta días de 23/25 h)."""
    return pd.date_range(inicio.tz_convert("UTC"), fin.tz_convert("UTC"), freq="15min", inclusive="left")


def alinear(s, idx, limite=3):
    """Pone una serie sobre la rejilla; rellena huecos de hasta `limite` cuartos
    (sirve para series horarias antiguas que se repiten 4 veces)."""
    if s is None or len(s) == 0:
        return pd.Series(np.nan, index=idx)
    s = s[~s.index.duplicated()].sort_index()
    paso = s.index.to_series().diff().median() if len(s) > 1 else pd.Timedelta(minutes=15)
    if paso < pd.Timedelta(minutes=59):
        # serie cuartohoraria: NO se rellena. Antes el ffill copiaba el último precio del IDA3
        # (que acaba a las 24:00) en los primeros cuartos del día siguiente, y el día sin IDA1
        # heredaba tres cuartos del anterior: medias y coberturas distintas de las de ESIOS.
        return s.reindex(idx)
    return s.reindex(idx.union(s.index)).ffill(limit=limite).reindex(idx)


def lunes_k(lunes, k):
    return lunes - timedelta(weeks=k)


def limites_semana(lunes):
    ini = pd.Timestamp(lunes).tz_localize(TZ)
    fin = pd.Timestamp(lunes + timedelta(days=7)).tz_localize(TZ)
    return ini, fin


# ---------------------------------------------------------------- batería
def dp_bateria(p, horas=4.0, rend=0.85, ciclado=4.0, ciclos_max=1.5, paso=0.25, p_venta=None):
    """Programación dinámica exacta para 1 MW / `horas` MWh en un día.

    Previsión perfecta de precios => es un TECHO teórico, no un ingreso real.
    Empieza y acaba vacía cada día y descarga como mucho `ciclos_max` veces su
    capacidad (los activos reales rondan 1-1,2 ciclos/día en el UNEF BESS Index).
    Devuelve (€/MW, acciones) con acciones: 0 = reposo, 1 = carga, 2 = descarga.
    """
    p = np.asarray(p, float)
    pv = p if p_venta is None else np.asarray(p_venta, float)   # precio de venta (por defecto, el mismo)
    n = len(p)
    S = int(round(horas / paso)) + 1            # niveles de carga
    C = int(round(ciclos_max * horas / paso))   # pasos de descarga permitidos
    eta = np.sqrt(rend)
    ok = ~np.isnan(p) & ~np.isnan(pv)
    pp = np.where(ok, p, 0.0)
    ppv = np.where(ok, pv, 0.0)
    NEG = -np.inf
    V = np.full((n + 1, S, C + 1), NEG)
    V[n, 0, :] = 0.0
    dec = np.zeros((n, S, C + 1), dtype=np.int8)
    for t in range(n - 1, -1, -1):
        nxt = V[t + 1]
        best = nxt.copy()
        d = np.zeros((S, C + 1), dtype=np.int8)
        if ok[t]:
            carga = np.full((S, C + 1), NEG)
            carga[:-1, :] = -pp[t] * paso / eta + nxt[1:, :]
            m = carga > best
            best = np.where(m, carga, best)
            d = np.where(m, 1, d)
            desc = np.full((S, C + 1), NEG)
            desc[1:, :-1] = (ppv[t] - ciclado) * paso * eta + nxt[:-1, 1:]
            m = desc > best
            best = np.where(m, desc, best)
            d = np.where(m, 2, d)
        V[t] = best
        dec[t] = d
    s, c = 0, 0
    acc = np.zeros(n, dtype=np.int8)
    for t in range(n):
        a = int(dec[t, s, c])
        acc[t] = a
        if a == 1:
            s += 1
        elif a == 2:
            s -= 1
            c += 1
    return float(V[0, 0, 0]), acc


def bess_por_dia(precio, bat):
    """{fecha_local: (ingreso €/MW, índice, acciones)} para cada día con >=90 % de datos."""
    dias = pd.Series(precio.index.tz_convert(TZ).date, index=precio.index)
    out = {}
    for d, g in precio.groupby(dias):
        if g.notna().mean() < 0.9:
            out[d] = (np.nan, g.index, None)
            continue
        v, acc = dp_bateria(
            g.values, bat["horas"], bat["rendimiento_ida_vuelta"], bat["coste_ciclado_eur_mwh"],
            bat.get("ciclos_max_dia", 1.5),
        )
        out[d] = (v, g.index, acc)
    return out


def bess_multimercado(spot, otros, bat):
    """Techo de arbitraje con el MEJOR precio disponible en cada cuarto de hora entre el diario y
    las subastas intradiarias (IDA1-3): compra al mínimo y vende al máximo. Previsión perfecta y
    sin límite de liquidez: es la cota superior del valor de reoptimizar la batería en intradiario.
    Devuelve {fecha: €/MW} solo para días con >= 90 % de datos del diario."""
    df = pd.concat([spot] + [o for o in otros if o is not None], axis=1)
    compra, venta = df.min(axis=1, skipna=True), df.max(axis=1, skipna=True)
    dias = pd.Series(spot.index.tz_convert(TZ).date, index=spot.index)
    out = {}
    for d, g in spot.groupby(dias):
        if g.notna().mean() < 0.9:
            continue
        v, _ = dp_bateria(compra.loc[g.index].values, bat["horas"], bat["rendimiento_ida_vuelta"], bat["coste_ciclado_eur_mwh"],
                          bat.get("ciclos_max_dia", 1.5), p_venta=venta.loc[g.index].values)
        out[d] = v
    return out


def spreads_tb(precio, horas=(1, 2, 4)):
    """Spread «top-bottom» de cada día: media de los k h más caras menos media de las k h más baratas
    (en cuartos de hora: 4k cuartos). Métrica estándar del sector para dimensionar baterías de k horas.
    Devuelve {k: media de la semana} con días de >= 90 % de datos."""
    dias = pd.Series(precio.index.tz_convert(TZ).date, index=precio.index)
    out = {}
    for k in horas:
        vals = []
        for _, g in precio.groupby(dias):
            if g.notna().mean() < 0.9:
                continue
            v = np.sort(g.dropna().values)
            q = 4 * k
            if len(v) >= 2 * q:
                vals.append(v[-q:].mean() - v[:q].mean())
        out[k] = float(np.mean(vals)) if vals else np.nan
    return out


# ---------------------------------------------------------------- utilidades
def minuto_local(idx):
    loc = idx.tz_convert(TZ)
    return loc.hour * 60 + loc.minute


def perfil_intradia(s):
    """Media por hora local del reloj (promedia el día de 25 h sin romperlo)."""
    return s.groupby(minuto_local(s.index)).mean()


def captura(precio, gen):
    m = precio.notna() & gen.notna() & (gen > 0)
    if m.sum() == 0 or gen[m].sum() == 0:
        return np.nan
    return float((precio[m] * gen[m]).sum() / gen[m].sum())


def ventana(acciones_por_dia, codigo):
    """Percentil 10-90 de la hora del reloj en que se carga (1) o descarga (2)."""
    horas = []
    for idx, acc in acciones_por_dia:
        if acc is None:
            continue
        mins = minuto_local(idx)[acc == codigo]
        horas.extend(list(mins / 60.0))
    if not horas:
        return None
    a, b = np.percentile(horas, [10, 90])
    return a, b


def matriz_calor(precio, acciones_por_dia, dias):
    """Matriz día x 96 cuartos de reloj. El domingo de 25 h promedia la hora repetida."""
    suma = np.zeros((len(dias), 96))
    cuenta = np.zeros((len(dias), 96))
    pos = {d: i for i, d in enumerate(dias)}
    loc = precio.index.tz_convert(TZ)
    for t, v, d in zip(loc, precio.values, loc.date):
        if d in pos and not np.isnan(v):
            k = t.hour * 4 + t.minute // 15
            suma[pos[d], k] += v
            cuenta[pos[d], k] += 1
    z = np.where(cuenta > 0, suma / np.maximum(cuenta, 1), np.nan)
    carga, desc = ([], []), ([], [])
    for d, idx, acc in acciones_por_dia:
        if acc is None or d not in pos:
            continue
        l = idx.tz_convert(TZ)
        for t, a in zip(l, acc):
            k = t.hour * 4 + t.minute // 15
            if a == 1:
                carga[0].append(k)
                carga[1].append(pos[d])
            elif a == 2:
                desc[0].append(k)
                desc[1].append(pos[d])
    return z, carga, desc


# ---------------------------------------------------------------- análisis principal
def analizar(datos, cfg, lunes):
    """datos: dict clave -> Serie UTC cruda. Devuelve el diccionario `res` del informe."""
    bat = cfg["bateria"]
    ini, fin = limites_semana(lunes)
    idx = rejilla(ini, fin)
    dias = sorted(set(idx.tz_convert(TZ).date))

    # 5 semanas de spot (actual + 4 anteriores)
    ini_base, _ = limites_semana(lunes_k(lunes, 4))
    idx5 = rejilla(ini_base, fin)
    spot5 = alinear(datos["spot"], idx5)
    spot = spot5.loc[idx]

    semanas = []
    for k in range(4, -1, -1):
        a, b = limites_semana(lunes_k(lunes, k))
        sl = spot5.loc[rejilla(a, b)]
        b5 = bess_por_dia(sl, bat)
        vals = [v[0] for v in b5.values() if not np.isnan(v[0])]
        iso = lunes_k(lunes, k).isocalendar()
        semanas.append(
            {
                "etiqueta": f"{iso.year}-S{iso.week:02d}",
                "corta": f"S{iso.week:02d}",
                "precio_medio": float(sl.mean()),
                "bess_dia": float(np.mean(vals)) if vals else np.nan,
                "bess_dias": b5 if k == 0 else None,
            }
        )
    act, prev = semanas[-1], semanas[-2]
    base4 = float(np.nanmean([s["precio_medio"] for s in semanas[:-1]]))

    b_act = act["bess_dias"]
    acciones = [(d, v[1], v[2]) for d, v in b_act.items()]
    z, carga, desc = matriz_calor(spot, acciones, dias)
    ingresos_dia = {d: v[0] for d, v in b_act.items()}

    # perfiles intradía
    perf_act = perfil_intradia(spot)
    prev4 = spot5.loc[idx5[idx5 < idx[0]]]
    perf_prev = perfil_intradia(prev4)

    # spreads diarios
    dia_idx = pd.Series(spot.index.tz_convert(TZ).date, index=spot.index)
    medias_dia = spot.groupby(dia_idx).mean()
    spread_dia = spot.groupby(dia_idx).agg(lambda g: g.max() - g.min())
    neg = int((spot <= 0).sum())

    res = {
        "lunes": lunes,
        "ini": ini,
        "fin": fin,
        "etiqueta": act["etiqueta"],
        "dias": dias,
        "spot": spot,
        "precio_medio": float(spot.mean()),
        "precio_min": float(spot.min()),
        "precio_max": float(spot.max()),
        "var_prev": (act["precio_medio"] / prev["precio_medio"] - 1) * 100 if prev["precio_medio"] else np.nan,
        "var_base4": (act["precio_medio"] / base4 - 1) * 100 if base4 else np.nan,
        "horas_neg": neg / 4.0,
        "spread_medio": float(spread_dia.mean()),
        "medias_dia": medias_dia,
        "bess_dia": act["bess_dia"],
        "bess_prev": prev["bess_dia"],
        "bess_semana": float(np.nansum(list(ingresos_dia.values()))),
        "bess_por_dia": ingresos_dia,
        "ventana_carga": ventana([(i, a) for _, i, a in acciones], 1),
        "ventana_desc": ventana([(i, a) for _, i, a in acciones], 2),
        "calor": z,
        "marcas_carga": carga,
        "marcas_desc": desc,
        "perfil_act": perf_act,
        "perfil_prev": perf_prev,
        "semanas": [{k: v for k, v in s.items() if k != "bess_dias"} for s in semanas],
        "cobertura": {},
        "extras": [],
        "demanda": None,
        "captura": {},
        "_bat_horas": bat["horas"],
        "series": {"spot": spot},
        "spot5": spot5,
        "gen5": {},
    }

    # demanda
    dr = alinear(datos.get("demanda_real"), idx)
    dp = alinear(datos.get("demanda_prevista"), idx)
    if dr.notna().mean() > 0.5:
        pico = dr.idxmax()
        d = {"real": dr, "pico": float(dr.max()), "pico_t": pico.tz_convert(TZ), "media": float(dr.mean()), "valle": float(dr.min())}
        if dp.notna().mean() > 0.5:
            m = dr.notna() & dp.notna() & (dr > 0)
            d["prevista"] = dp
            d["mape"] = float((abs(dr[m] - dp[m]) / dr[m]).mean() * 100)
        res["demanda"] = d

    for k, v in datos.items():
        if k != "spot":
            res["series"][k] = alinear(v, idx)
        if k in ("gen_solar_fv", "gen_eolica"):
            res["gen5"][k] = alinear(v, idx5)

    # generación y precios capturados
    for k in ("gen_solar_fv", "gen_eolica"):
        g = alinear(datos.get(k), idx)
        if g.notna().mean() > 0.5:
            c = captura(spot, g)
            res["captura"][k] = {
                "precio": c,
                "ratio": c / res["precio_medio"] * 100 if res["precio_medio"] else np.nan,
                "energia_gwh": float(g.sum() / 4 / 1000),
            }

    # otros mercados
    for k, v in cfg.get("opcionales", {}).items():
        if v.get("tipo") == "precio" and k in datos:
            s = alinear(datos[k], idx)
            if s.notna().mean() > 0.3:
                res["extras"].append(
                    {
                        "clave": k,
                        "nombre": v["nombre"],
                        "media": float(s.mean()),
                        "min": float(s.min()),
                        "max": float(s.max()),
                        # diferencia en los MISMOS cuartos de hora: el IDA3 solo cubre 12:00-24:00
                        # y compararlo con la media del día entero lo sesgaba al alza
                        "dif": float((s - spot).mean()),
                        "cubre": float(s.notna().mean()),
                        "serie": s,
                    }
                )

    # mix de generación y baterías del sistema (tiempo real); si algo falla, la sección se omite
    for clave, fn in (("mix", lambda: mix_semana(datos, cfg, idx)), ("baterias", lambda: baterias_semana(datos, idx, spot, res))):
        try:
            res[clave] = fn()
        except Exception as e:
            print(f"AVISO: {clave} omitido ({type(e).__name__}: {str(e)[:100]})")
            res[clave] = None

    # spreads top-bottom y techo multimercado (diario + subastas intradiarias)
    try:
        res["tb"] = spreads_tb(spot)
        otros = [res["series"].get(k) for k in ("ida1", "ida2", "ida3")]
        if any(o is not None and o.notna().mean() > 0.3 for o in otros):
            mm = bess_multimercado(spot, otros, bat)
            if mm:
                solo = {d: v for d, v in ingresos_dia.items() if d in mm and not np.isnan(v)}
                res["multimercado"] = {
                    "por_dia": mm, "solo_diario": solo,
                    "media": float(np.mean(list(mm.values()))),
                    "media_diario": float(np.mean(list(solo.values()))) if solo else np.nan,
                }
                md = res["multimercado"]
                md["uplift"] = (md["media"] / md["media_diario"] - 1) * 100 if md["media_diario"] else np.nan
    except Exception as e:
        print(f"AVISO: spreads/multimercado omitidos ({type(e).__name__}: {str(e)[:100]})")
        res.setdefault("tb", {})

    # cobertura de todas las series
    res["cobertura"]["spot"] = float(spot.notna().mean())
    for k in list(datos):
        if k != "spot" and not k.startswith(("mix_", "bal_")):
            res["cobertura"][k] = float(alinear(datos[k], idx).notna().mean())
    return res


# ---------------------------------------------------------------- mix y baterías
def mix_semana(datos, cfg, idx):
    """Mix peninsular en tiempo real (MW cada 5 min, promediado a 15 min).

    La hidráulica de ESIOS (546) va en NETO: incluye la turbinación (2079) y el consumo de
    bombeo (2078). Para la cuota renovable se separa: hidráulica convencional = 546 - 2079 - 2078,
    y la turbinación de bombeo cuenta como no renovable (criterio de REE). Comprobado: generación
    + intercambios + enlace balear + baterías cierra con la demanda real con un -0,7 % (semana 44)."""
    conf = cfg.get("mix") or {}
    if not conf:
        return None
    s = {k: alinear(datos.get(f"mix_{k}"), idx) for k in conf}
    if not s or np.mean([v.notna().mean() for v in s.values()]) < 0.5:
        return None
    bal = {k: alinear(datos.get(f"bal_{k}"), idx) for k in (cfg.get("balance") or {})}
    if "hidraulica" in s:
        bomb = bal.get("turb_bombeo", pd.Series(0.0, index=idx)).fillna(0) + bal.get("cons_bombeo", pd.Series(0.0, index=idx)).fillna(0)
        s["hidraulica"] = (s["hidraulica"] - bomb).clip(lower=0)
        if "turb_bombeo" in bal:
            s["turb_bombeo"] = bal["turb_bombeo"].clip(lower=0)
    nombres = {k: v["nombre"] for k, v in conf.items()}
    renov = {k for k, v in conf.items() if v.get("renovable")}
    if "turb_bombeo" in s:
        nombres["turb_bombeo"] = "Turbinación bombeo"
    gen = pd.DataFrame(s).clip(lower=0)
    total = gen.sum(axis=1, min_count=1)
    e = gen.sum() / 4 / 1000                                                   # GWh
    ren = gen[[k for k in gen.columns if k in renov]].sum(axis=1)
    dem = alinear(datos.get("demanda_real"), idx)
    out = {
        "series": gen, "nombres": nombres, "renovables": renov,
        "gwh": e.sort_values(ascending=False), "cuota": (e / e.sum() * 100).sort_values(ascending=False),
        "renovable_pct": float(ren.sum() / total.sum() * 100) if total.sum() else np.nan,
        "renovable_max": float((ren / total).max() * 100) if total.notna().any() else np.nan,
        "renovable_min": float((ren / total).min() * 100) if total.notna().any() else np.nan,
        "horas_ren_demanda": float(((ren >= dem) & dem.notna()).sum() / 4) if dem.notna().any() else np.nan,
    }
    if "intercambios" in bal and bal["intercambios"].notna().mean() > 0.5:
        x = bal["intercambios"]
        out["saldo_intercambios_gwh"] = float(x.sum() / 4 / 1000)          # negativo = exportación neta
        out["horas_exportando"] = float((x < 0).sum() / 4)
    return out


def baterias_semana(datos, idx, spot, res):
    """Parque de baterías peninsular en tiempo real (2166 carga, 2167 entrega)."""
    c, e = alinear(datos.get("bal_bat_carga"), idx), alinear(datos.get("bal_bat_entrega"), idx)
    if c.notna().mean() < 0.5 or e.notna().mean() < 0.5:
        return None
    carga = (-c).clip(lower=0)                                                 # ESIOS publica la carga en negativo
    entrega = e.clip(lower=0)
    mc, md = carga.sum() / 4, entrega.sum() / 4                                 # MWh
    def pond(p, w):
        m = p.notna() & w.notna() & (w > 0)
        return float((p[m] * w[m]).sum() / w[m].sum()) if w[m].sum() > 0 else np.nan
    pc, pdesc = pond(spot, carga), pond(spot, entrega)
    neto = entrega.fillna(0) - carga.fillna(0)
    return {
        "carga": carga, "entrega": entrega, "neto": neto,
        "mwh_carga": float(mc), "mwh_entrega": float(md),
        "mw_max_carga": float(carga.max()), "mw_max_entrega": float(entrega.max()),
        "rendimiento": float(md / mc * 100) if mc > 0 else np.nan,
        "precio_carga": pc, "precio_descarga": pdesc,
        "spread": pdesc - pc if not (np.isnan(pc) or np.isnan(pdesc)) else np.nan,
        "ingreso_neto": float(((entrega.fillna(0) - carga.fillna(0)) * spot.fillna(0)).sum() / 4),
        "perfil_neto": perfil_intradia(neto),
    }
