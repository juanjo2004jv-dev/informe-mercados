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
    return s.reindex(idx.union(s.index)).ffill(limit=limite).reindex(idx)


def lunes_k(lunes, k):
    return lunes - timedelta(weeks=k)


def limites_semana(lunes):
    ini = pd.Timestamp(lunes).tz_localize(TZ)
    fin = pd.Timestamp(lunes + timedelta(days=7)).tz_localize(TZ)
    return ini, fin


# ---------------------------------------------------------------- batería
def dp_bateria(p, horas=4.0, rend=0.85, ciclado=4.0, ciclos_max=1.5, paso=0.25):
    """Programación dinámica exacta para 1 MW / `horas` MWh en un día.

    Previsión perfecta de precios => es un TECHO teórico, no un ingreso real.
    Empieza y acaba vacía cada día y descarga como mucho `ciclos_max` veces su
    capacidad (los activos reales rondan 1-1,2 ciclos/día en el UNEF BESS Index).
    Devuelve (€/MW, acciones) con acciones: 0 = reposo, 1 = carga, 2 = descarga.
    """
    p = np.asarray(p, float)
    n = len(p)
    S = int(round(horas / paso)) + 1            # niveles de carga
    C = int(round(ciclos_max * horas / paso))   # pasos de descarga permitidos
    eta = np.sqrt(rend)
    ok = ~np.isnan(p)
    pp = np.where(ok, p, 0.0)
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
            desc[1:, :-1] = (pp[t] - ciclado) * paso * eta + nxt[:-1, 1:]
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
                        "dif": float(s.mean() - res["precio_medio"]),
                        "serie": s,
                    }
                )

    # cobertura de todas las series
    res["cobertura"]["spot"] = float(spot.notna().mean())
    for k in list(datos):
        if k != "spot":
            res["cobertura"][k] = float(alinear(datos[k], idx).notna().mean())
    return res
