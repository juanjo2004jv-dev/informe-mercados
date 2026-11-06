"""Redacción automática en español a partir de las métricas (sin IA, sin coste)."""
import numpy as np

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
DIAS_LARGO = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def n(x, d=1, signo=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "s/d"
    if round(x, d) == 0:
        x = 0.0
    s = f"{x:+,.{d}f}" if signo and x != 0 else f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def hhmm(h):
    h = h % 24
    return f"{int(h):02d}:{int(round((h - int(h)) * 60)) % 60:02d}"


def etiqueta_dia(d):
    return f"{DIAS[d.weekday()]} {d.day}"


def rango(res):
    a, b = res["dias"][0], res["dias"][-1]
    if a.month == b.month:
        return f"{a.day}–{b.day} {MESES[b.month - 1]} {b.year}"
    return f"{a.day} {MESES[a.month - 1]} – {b.day} {MESES[b.month - 1]} {b.year}"


def _tendencia(v, umbral=3.0):
    if np.isnan(v):
        return "sin referencia"
    if v > umbral:
        return f"{n(v, 1, True)} % por encima"
    if v < -umbral:
        return f"{n(abs(v), 1)} % por debajo"
    return "en línea"


def redactar(res):
    t = {}
    pm, vp = res["precio_medio"], res["var_prev"]
    sem = int(res["etiqueta"].split("S")[1])
    t["titular"] = (
        f"El precio medio del mercado diario fue de {n(pm)} €/MWh, "
        f"{n(vp, 1, True)} % frente a la semana anterior, con {n(res['horas_neg'], 1)} h a precio ≤ 0. "
        f"Una batería de {int(res['_bat_horas'])} h con previsión perfecta habría podido captar "
        f"hasta {n(res['bess_dia'], 0)} €/MW al día."
    )

    # --- mercado
    md = res["medias_dia"]
    dmax, dmin = md.idxmax(), md.idxmin()
    perf = res["perfil_act"]
    hmin, hmax = perf.idxmin() / 60, perf.idxmax() / 60
    t["h_calor"] = (
        f"El precio medio cayó a {n(perf.min())} €/MWh a las {hhmm(hmin)} "
        f"y subió a {n(perf.max())} €/MWh a las {hhmm(hmax)}"
    )
    t["p_calor"] = (
        f"Cada fila es un día y cada columna un cuarto de hora. El día más caro fue el "
        f"{DIAS_LARGO[dmax.weekday()]} {dmax.day} ({n(md.max())} €/MWh de media) y el más barato el "
        f"{DIAS_LARGO[dmin.weekday()]} {dmin.day} ({n(md.min())} €/MWh). "
        f"La semana quedó {_tendencia(res['var_base4'])} de la media de las cuatro anteriores. "
        f"El spread medio entre el cuarto de hora más caro y el más barato de cada día fue de {n(res['spread_medio'])} €/MWh."
    )
    if res["spot"].index.tz_convert("Europe/Madrid").normalize().nunique() and any(
        len(g) != 96 for _, g in res["spot"].groupby(res["spot"].index.tz_convert("Europe/Madrid").date)
    ):
        t["p_calor"] += (
            " Esta semana incluye un cambio de hora: ese día tiene 92 o 100 cuartos de hora, "
            "y en el mapa la hora repetida se promedia."
        )

    # --- batería
    pd_ = {d: v for d, v in res["bess_por_dia"].items() if not np.isnan(v)}
    if pd_:
        mejor = max(pd_, key=pd_.get)
        peor = min(pd_, key=pd_.get)
        t["h_bess"] = (
            f"El mejor día para almacenar fue el {DIAS_LARGO[mejor.weekday()]} {mejor.day}: "
            f"{n(pd_[mejor], 0)} €/MW"
        )
        frases = [
            f"El peor fue el {DIAS_LARGO[peor.weekday()]} {peor.day} ({n(pd_[peor], 0)} €/MW). "
            f"La media diaria fue de {n(res['bess_dia'], 0)} €/MW, "
            f"{n((res['bess_dia'] / res['bess_prev'] - 1) * 100, 1, True) if res['bess_prev'] else 's/d'} % frente a la semana anterior."
        ]
        if res["ventana_carga"] and res["ventana_desc"]:
            a, b = res["ventana_carga"]
            c, d = res["ventana_desc"]
            frases.append(
                f"La carga óptima se concentró entre las {hhmm(a)} y las {hhmm(b)}, y la descarga entre las {hhmm(c)} y las {hhmm(d)}."
            )
        t["p_bess"] = " ".join(frases)
    else:
        t["h_bess"] = "No hay datos suficientes para calcular el arbitraje"
        t["p_bess"] = ""

    # --- tendencia
    s = res["semanas"]
    t["h_tend"] = (
        "El techo de arbitraje sube respecto a las semanas anteriores"
        if s[-1]["bess_dia"] > np.nanmean([x["bess_dia"] for x in s[:-1]])
        else "El techo de arbitraje baja respecto a las semanas anteriores"
    )

    # --- solar / eólica
    cs = res["captura"]
    if "gen_solar_fv" in cs:
        c = cs["gen_solar_fv"]
        t["h_solar"] = (
            f"La solar cobró de media {n(c['precio'])} €/MWh, el {n(c['ratio'], 0)} % del precio medio"
        )
        t["p_solar"] = (
            "El precio capturado pondera cada cuarto de hora por la generación del mismo. "
            "Cuanto más lejos del 100 %, más pierde la solar por producir justo cuando el mercado está barato."
        )
        if "gen_eolica" in cs:
            e = cs["gen_eolica"]
            t["p_solar"] += f" La eólica capturó {n(e['precio'])} €/MWh ({n(e['ratio'], 0)} %)."

    # --- demanda
    d = res["demanda"]
    if d:
        t["h_dem"] = f"La demanda alcanzó {n(d['pico'], 0)} MW el {DIAS_LARGO[d['pico_t'].weekday()]} {d['pico_t'].day} a las {d['pico_t'].strftime('%H:%M')}"
        t["p_dem"] = f"Media semanal de {n(d['media'], 0)} MW y valle de {n(d['valle'], 0)} MW."
        if "mape" in d:
            t["p_dem"] += f" El error medio de la previsión fue del {n(d['mape'], 2)} %."
    return t
