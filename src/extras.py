"""Apartados propios de inteligencia de mercado para almacenamiento y renovables.
Todo se calcula con los mismos datos públicos (ESIOS); nada de esto está en el informe de referencia."""
import textwrap

import numpy as np
import pandas as pd
from matplotlib.patches import Circle, Rectangle

from . import analisis as A
from .narrativa import DIAS_LARGO, etiqueta_dia, hhmm, n
from .pdf import C, PALETA, _ejes_dias, _leyenda

ROJO, AMBAR, VERDE = "#C0392B", "#E0A030", "#3E9E5B"


def _horas(s):
    return s.groupby(A.minuto_local(s.index) // 60).mean()


# ----------------------------------------------------------------- cálculo
def bess_duraciones(res, cfg, duraciones=(1, 2, 4, 6)):
    """Ingreso medio diario (€/MW·día) del techo de arbitraje según horas de duración."""
    out = {}
    for h in duraciones:
        bat = dict(cfg["bateria"], horas=h)
        r = A.bess_por_dia(res["spot"], bat)
        v = [x[0] for x in r.values() if not np.isnan(x[0])]
        out[h] = float(np.mean(v)) if v else np.nan
    return out


def banda_vs_arbitraje(res, cfg):
    """Por día: arbitraje 4 h frente a reservar 1 MW de banda aFRR simétrica todo el día (aproximación)."""
    sub = res["series"].get("afrr_banda_p_subir")
    baj = res["series"].get("afrr_banda_p_bajar")
    if sub is None or baj is None or sub.notna().mean() < 0.3 or baj.notna().mean() < 0.3:
        return None
    dias = pd.Series(res["spot"].index.tz_convert(A.TZ).date, index=res["spot"].index)
    banda = ((sub.fillna(0) + baj.fillna(0)) * 0.25).groupby(dias).sum()          # €/MW·día (precio €/MW·h × 0,25 h)
    cob = (sub.notna() & baj.notna()).groupby(dias).mean()
    banda = banda.where(cob >= 0.9)                                                 # día sin precio publicado: sin dato, no cero
    arb = pd.Series(res["bess_por_dia"])
    df = pd.DataFrame({"arbitraje": arb, "banda": banda}).dropna()
    return None if df.empty else df


def sensibilidad_residual(res):
    """Pendiente del precio frente a la demanda residual (demanda − FV − eólica)."""
    s = res["series"]
    if not all(k in s for k in ("demanda_real", "gen_solar_fv", "gen_eolica")):
        return None
    dr, fv, eo = s["demanda_real"], s["gen_solar_fv"], s["gen_eolica"]
    df = pd.DataFrame({"p": res["spot"], "res": (dr - fv - eo) / 1000.0}).dropna()
    if len(df) < 200:
        return None
    df = df.groupby(df.index.floor("h")).mean()
    k = np.polyfit(df["res"], df["p"], 1)
    r = float(np.corrcoef(df["res"], df["p"])[0, 1])
    return df, k, r


def canibalizacion(res):
    """Ratio de captura (%) de FV y eólica en cada una de las 5 semanas."""
    out = {}
    for k, g5 in res["gen5"].items():
        if g5.notna().mean() < 0.5:
            continue
        vals = []
        for kk in range(4, -1, -1):
            lun = A.lunes_k(res["lunes"], kk)
            a, b = A.limites_semana(lun)
            idx = A.rejilla(a, b)
            sp = res["spot5"].reindex(idx)
            g = g5.reindex(idx)
            c = A.captura(sp, g)
            vals.append(c / sp.mean() * 100 if sp.mean() else np.nan)
        out[k] = vals
    return out


def senales(res, cfg, bd):
    """Semáforo por perfil. Reglas simples y transparentes (se enseñan en pantalla)."""
    fil = []
    um = cfg.get("semaforos") or {}                       # umbrales de config.yml (convenciones de este informe)
    a1, a2 = um.get("captura_fv_pct", [70, 85])
    cs = res["captura"].get("gen_solar_fv")
    if cs:
        r = cs["ratio"]
        est = (ROJO, "Canibalización alta") if r < a1 else (AMBAR, "Canibalización moderada") if r < a2 else (VERDE, "Captura sana")
        fil.append(("Promotor solar FV", est, f"Captura {n(r, 0)} % del precio medio. Regla: <{n(a1, 0)} % rojo, {n(a1, 0)}-{n(a2, 0)} % ámbar, >{n(a2, 0)} % verde."))
    else:
        fil.append(("Promotor solar FV", (C["gris"], "Sin dato"), "Falta la serie de generación solar (ver config.yml)."))
    b, p = res["bess_dia"], np.nanmean([x["bess_dia"] for x in res["semanas"][:-1]])
    v = (b / p - 1) * 100 if p else np.nan
    tv = um.get("techo_var_pct", 10)
    est = (VERDE, "Techo al alza") if v > tv else (ROJO, "Techo a la baja") if v < -tv else (AMBAR, "Techo estable")
    fil.append(("Almacenamiento (arbitraje)", est, f"{n(b, 0)} €/MW·día, {n(v, 1, True)} % frente a la media de 4 semanas. Regla: ±{n(tv, 0)} %."))
    sp = res["spread_medio"]
    s1, s2 = um.get("spread_eur_mwh", [60, 120])
    est = (VERDE, "Spread amplio") if sp > s2 else (AMBAR, "Spread medio") if sp > s1 else (ROJO, "Spread estrecho")
    tb4 = (res.get("tb") or {}).get(4)
    extra = f" TB4 {n(tb4, 0)} €/MWh." if tb4 == tb4 and tb4 is not None else ""
    fil.append(("Volatilidad intradía", est, f"Spread diario medio {n(sp, 0)} €/MWh.{extra} Regla: >{n(s2, 0)} verde, {n(s1, 0)}-{n(s2, 0)} ámbar, <{n(s1, 0)} rojo."))
    mm = res.get("multimercado")
    if mm and mm.get("uplift") == mm.get("uplift"):
        u = mm["uplift"]
        i1, i2 = (cfg.get("semaforos") or {}).get("intradiario_uplift_pct", [8, 20])
        est = (VERDE, "Intradiario aporta mucho") if u > i2 else (AMBAR, "Intradiario aporta algo") if u > i1 else (ROJO, "Intradiario aporta poco")
        fil.append(("Arbitraje en intradiario", est, f"Techo con diario + IDA1-3: {n(mm['media'], 0)} €/MW·día ({n(u, 0, True)} % sobre solo diario). Regla: >{n(i2, 0)} % verde, {n(i1, 0)}-{n(i2, 0)} % ámbar."))
    pr = bd.get("prima_afrr")
    if pr is not None:
        p1, p2 = um.get("prima_afrr_eur_mwh", [8, 25])
        est = (VERDE, "Prima de balance alta") if pr > p2 else (AMBAR, "Prima moderada") if pr > p1 else (ROJO, "Prima baja")
        fil.append(("Servicios de balance", est, f"aFRR a subir paga {n(pr, 1, True)} €/MWh sobre el diario ({bd.get('prima_afrr_tipo', '')}). Regla: >{n(p2, 0)} verde, {n(p1, 0)}-{n(p2, 0)} ámbar."))
    d = res["demanda"]
    if d and "mape" in d:
        m1, m2 = um.get("mape_demanda_pct", [1.5, 3])
        est = (VERDE, "Previsión precisa") if d["mape"] < m1 else (AMBAR, "Desvíos moderados") if d["mape"] < m2 else (ROJO, "Desvíos altos")
        fil.append(("Calidad de previsión", est, f"Error medio de la previsión de demanda {n(d['mape'], 2)} %. Regla: <{n(m1, 1)} % verde, {n(m1, 1)}-{n(m2, 0)} % ámbar, >{n(m2, 0)} % rojo."))
    hn = res["horas_neg"]
    h1, h2 = um.get("horas_neg_h", [3, 15])
    est = (ROJO, "Muchas horas ≤ 0") if hn > h2 else (AMBAR, "Horas ≤ 0 presentes") if hn > h1 else (VERDE, "Pocas horas ≤ 0")
    fil.append(("Precios cero y negativos", est, f"{n(hn, 1)} h a precio ≤ 0. Regla: >{n(h2, 0)} h rojo, {n(h1, 0)}-{n(h2, 0)} h ámbar, <{n(h1, 0)} h verde."))
    return fil


def resumen_extras(res, cfg):
    bd = {}
    s = res["series"].get("afrr_subir")
    if s is not None and s.notna().mean() > 0.3:
        bd["prima_afrr"] = float((s - res["spot"]).mean())
        bd["prima_afrr_tipo"] = "media simple"
        act = res["series"].get("afrr_energia_act_subir")
        if act is not None and act.notna().mean() > 0.3:
            m = s.notna() & res["spot"].notna() & act.notna() & (act > 0)
            if m.sum() and act[m].sum() > 0:
                # lo que importa a quien presta el servicio es el precio cuando le activan:
                # se pondera por la energía activada a subir (ID 680)
                bd["prima_afrr"] = float(((s - res["spot"])[m] * act[m]).sum() / act[m].sum())
                bd["prima_afrr_tipo"] = "ponderada por energía activada"
    return bd


# ----------------------------------------------------------------- diapositivas
def sec_senales(d, res, cfg):
    bd = resumen_extras(res, cfg)
    fil = senales(res, cfg, bd)
    fig = d.diapositiva("Señales de la semana para cada perfil",
                        "Un semáforo por perfil con reglas explícitas y sencillas. No son una recomendación de inversión: resumen en una mirada qué se movió y para quién importa.",
                        "Fuente: ESIOS (REE) y OMIE. Elaboración propia; los umbrales son convenciones de este informe, no estándares del sector.")
    y = 0.72
    for nom, (col, etiqueta), txt in fil:
        fig.add_artist(Rectangle((0.05, y - 0.052), 0.90, 0.062, color=C["panel"], transform=fig.transFigure))
        fig.add_artist(Rectangle((0.05, y - 0.052), 0.008, 0.062, color=col, transform=fig.transFigure))
        fig.text(0.07, y - 0.012, nom, fontsize=11.5, fontweight="bold", va="center", color=C["verde"])
        fig.text(0.07, y - 0.036, textwrap.shorten(txt, 118, placeholder="…"), fontsize=8.5, va="center", color=C["gris"])
        fig.add_artist(Circle((0.745, y - 0.021), 0.011, color=col, transform=fig.transFigure))
        fig.text(0.765, y - 0.021, etiqueta, fontsize=10, fontweight="bold", va="center", color=col)
        y -= 0.075
    d.guardar(fig)


def sec_duracion_precios(d, res):
    s = res["spot"].dropna().sort_values(ascending=False).values
    fig = d.diapositiva("Curva de duración de precios",
                        f"Los {len(s)} cuartos de hora de la semana ordenados de más caro a más barato. {n(res['horas_neg'], 1)} h cerraron a precio cero o negativo y "
                        f"el {n((res['spot'] > 200).mean() * 100, 1)} % del tiempo superó los 200 €/MWh. La anchura de la curva es la materia prima del arbitraje.",
                        "Fuente: OMIE vía ESIOS, mercado diario, 15 minutos.")
    ax = d.eje(fig)
    x = np.arange(len(s)) / 4
    ax.fill_between(x, s, 0, where=s > 0, color=C["verde"], alpha=0.25)
    ax.fill_between(x, s, 0, where=s <= 0, color=C["coral"], alpha=0.5)
    ax.plot(x, s, color=C["verde"], lw=2.4)
    ax.axhline(res["precio_medio"], color=C["gris"], ls="--", lw=1.2)
    ax.text(x[-1], res["precio_medio"], f" media {n(res['precio_medio'], 0)}", va="bottom", ha="right", fontsize=9, color=C["gris"])
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_xlabel("Horas de la semana (ordenadas)")
    ax.set_ylabel("€/MWh")
    d.guardar(fig)


def sec_rango_diario(d, res):
    sp = res["spot"]
    dia = pd.Series(sp.index.tz_convert(A.TZ).date, index=sp.index)
    g = sp.groupby(dia).agg(["min", "max", "mean"])
    fig = d.diapositiva("Rango de precios de cada día",
                        f"Cada barra va del cuarto de hora más barato al más caro del día; el punto es la media. El spread medio fue de {n(res['spread_medio'], 0)} €/MWh. "
                        "Un spread alto con mínimos negativos es el escenario que más valor da a una batería.", "Fuente: OMIE vía ESIOS, mercado diario, 15 minutos.")
    ax = d.eje(fig)
    for i, (k, r_) in enumerate(g.iterrows()):
        ax.bar(i, r_["max"] - r_["min"], 0.5, bottom=r_["min"], color=C["verde"], alpha=0.85)
        ax.plot(i, r_["mean"], "o", color=C["coral"], ms=8, zorder=3)
        ax.text(i, r_["max"] + 5, n(r_["max"], 0), ha="center", fontsize=9)
        ax.text(i, r_["min"] - 14, n(r_["min"], 0), ha="center", fontsize=9, va="top")
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_ylim(min(0, g["min"].min()) - 45, g["max"].max() * 1.1)
    ax.set_xticks(range(len(g)))
    ax.set_xticklabels([etiqueta_dia(k) for k in g.index])
    ax.set_ylabel("€/MWh")
    d.guardar(fig)


def sec_duraciones(d, res, cfg):
    r = bess_duraciones(res, cfg)
    fig = d.diapositiva("¿Cuánto vale cada hora de duración?",
                        "Techo de arbitraje del mercado diario para la misma semana con baterías de 1, 2, 4 y 6 horas. A la izquierda, ingreso por MW de potencia; a la derecha, "
                        "por MWh instalado: la métrica con la que se compara el coste de capital de cada configuración.",
                        "Fuente: OMIE vía ESIOS. Cálculo propio: programación dinámica con previsión perfecta, 85 % de rendimiento, 4 €/MWh de ciclado y tope de ciclos por día.")
    hs = list(r)
    for k, (tit, vals, uni) in enumerate(((" Por MW de potencia", [r[h] for h in hs], "€/MW·día"), (" Por MWh instalado", [r[h] / h for h in hs], "€/MWh·día"))):
        ax = d.eje(fig, caja=[0.07 + k * 0.48, 0.14, 0.41, 0.57])
        bars = ax.bar(range(len(hs)), vals, 0.55, color=[PALETA[1], PALETA[3], C["coral"], PALETA[2]])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v * 1.01, n(v, 0), ha="center", fontsize=10, fontweight="bold")
        ax.set_xticks(range(len(hs)))
        ax.set_xticklabels([f"{h} h" for h in hs])
        ax.set_ylabel(uni)
        ax.set_title(tit, fontsize=10.5, color=C["verde"], loc="left")
    d.guardar(fig)
    return r


def sec_banda(d, res, cfg):
    bb = banda_vs_arbitraje(res, cfg)
    if bb is None:
        return False
    fig = d.diapositiva("Arbitraje frente a reservar banda aFRR",
                        "Para una batería de 1 MW: lo que habría dado el arbitraje del diario frente a ofrecer 1 MW de banda aFRR simétrica todo el día. No se suman, porque la "
                        "misma potencia no puede estar en los dos sitios, pero comparar ambos muestra qué mercado domina cada día.",
                        "Fuente: ESIOS (REE) y OMIE. La banda se aproxima como Σ(precio a subir + precio a bajar) × 0,25 h por cuarto de hora, sin activación ni penalizaciones. Aproximación, no liquidación."
                        + (" " + res["nota_banda"] if res.get("nota_banda") else ""))
    ax = d.eje(fig)
    x = np.arange(len(bb))
    ax.bar(x - 0.2, bb["arbitraje"], 0.38, color=C["verde"], label="Arbitraje (diario, 4 h)")
    ax.bar(x + 0.2, bb["banda"], 0.38, color=C["mostaza"], label="Banda aFRR simétrica (1 MW)")
    for i, (a, b) in enumerate(zip(bb["arbitraje"], bb["banda"])):
        ax.text(i - 0.2, a * 1.01, n(a, 0), ha="center", fontsize=8.5)
        ax.text(i + 0.2, b * 1.01, n(b, 0), ha="center", fontsize=8.5)
    ax.set_xticks(x)
    ax.set_xticklabels([etiqueta_dia(k) for k in bb.index])
    ax.set_ylabel("€/MW·día")
    _leyenda(ax, 2)
    d.guardar(fig)
    return True


def sec_primas(d, res, cfg):
    """Prima de cada mercado sobre el diario, por hora del día."""
    sp = res["spot"]
    lineas = []
    for k, v in cfg.get("opcionales", {}).items():
        if v.get("tipo") == "precio" and k in res["series"] and res["series"][k].notna().mean() > 0.3:
            lineas.append((v["nombre"], _horas(res["series"][k] - sp)))
    if len(lineas) < 2:
        return False
    fig = d.diapositiva("Dónde paga más cada mercado respecto al diario, hora a hora",
                        "Diferencia media entre el precio de cada mercado y el del diario en cada hora del día. Por encima de cero, ese mercado paga más que el diario a esa hora: "
                        "es donde un activo flexible encuentra una segunda oportunidad después del arbitraje.",
                        "Fuente: ESIOS (REE) y OMIE. Media de la semana por hora local.")
    ax = d.eje(fig)
    for i, (nom, s) in enumerate(lineas):
        ax.plot(s.index, s.values, lw=2 if "aFRR" in nom or "mFRR" in nom else 1.4, color=PALETA[i % len(PALETA)], label=nom)
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)])
    ax.set_ylabel("€/MWh sobre el diario")
    _leyenda(ax, 4)
    d.guardar(fig)
    return True


def sec_canibalizacion(d, res):
    c = canibalizacion(res)
    if not c:
        return False
    nom = {"gen_solar_fv": "Solar FV", "gen_eolica": "Eólica"}
    cor = {"gen_solar_fv": C["coral"], "gen_eolica": C["azul"]}
    fv = c.get("gen_solar_fv")
    fig = d.diapositiva("Canibalización: cuánto del precio medio llega a cobrar cada tecnología",
                        "Ratio de captura (precio capturado entre precio medio del diario) en las últimas cinco semanas. Un 100 % significa cobrar lo que cuesta de media la energía; "
                        "por debajo, la tecnología produce justo cuando el mercado está barato." + (f" Esta semana la solar capturó el {n(fv[-1], 0)} %." if fv else ""),
                        "Fuente: ESIOS (REE). Precio diario ponderado por generación en tiempo real. Aproximación: no es la liquidación del I3.")
    ax = d.eje(fig)
    et = [s["corta"] for s in res["semanas"]]
    for k, v in c.items():
        ax.plot(et, v, marker="o", lw=3, color=cor[k], label=nom[k])
        for i, x in enumerate(v):
            ax.text(i, x + 2, f"{n(x, 0)} %", ha="center", fontsize=9, color=cor[k], fontweight="bold")
    ax.axhline(100, color=C["gris"], ls="--", lw=1)
    ax.set_ylabel("% del precio medio")
    ax.set_ylim(0, 120)
    _leyenda(ax, 2)
    d.guardar(fig)
    return True


def sec_residual(d, res):
    r = sensibilidad_residual(res)
    if r is None:
        return False
    df, k, rho = r
    fig = d.diapositiva("Qué mueve el precio: la demanda residual",
                        f"Cada punto es una hora. La demanda residual es lo que queda por cubrir con tecnologías no renovables (demanda − solar − eólica). La pendiente de la recta indica que "
                        f"cada GW más de demanda residual sube el precio unos {n(k[0], 1)} €/MWh (correlación {n(rho, 2)}).",
                        "Fuente: ESIOS (REE) y OMIE. Medias horarias de la semana. Es una relación descriptiva, no un modelo de formación de precios.")
    ax = d.eje(fig, caja=[0.08, 0.15, 0.86, 0.57])
    h = df.index.tz_convert(A.TZ).hour
    sc = ax.scatter(df["res"], df["p"], c=h, cmap="viridis", s=34, alpha=0.85, edgecolor="white", lw=0.4)
    xs = np.linspace(df["res"].min(), df["res"].max(), 50)
    ax.plot(xs, np.polyval(k, xs), color=C["coral"], lw=2.5)
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_xlabel("Demanda residual (GW)")
    ax.set_ylabel("Precio del diario (€/MWh)")
    cb = fig.colorbar(sc, ax=ax, fraction=0.025, pad=0.02)
    cb.set_label("Hora del día")
    cb.outline.set_visible(False)
    d.guardar(fig)
    return True


def sec_glosario(d):
    fig = d.diapositiva("Glosario", None, "Definiciones simplificadas con fines divulgativos; la referencia es la normativa y los procedimientos de operación de REE.")
    items = [
        ("PBF", "Programa Base de Funcionamiento: sale del mercado diario y los contratos bilaterales, antes de resolver restricciones."),
        ("PDVP", "Programa Diario Viable Provisional: el PBF tras resolver las restricciones técnicas del diario."),
        ("PHF", "Programa Horario Final: el PDVP tras las sesiones de mercado intradiario."),
        ("P48", "Programa físico definitivo que queda tras las restricciones en tiempo real y los servicios de balance."),
        ("IDA / continuo", "Subastas intradiarias (IDA1, IDA2, IDA3) y mercado intradiario continuo."),
        ("aFRR / mFRR", "Reservas de regulación secundaria (automática) y terciaria (manual) que contrata el operador."),
        ("Banda aFRR", "Potencia reservada para regulación secundaria; se paga en €/MW, no en €/MWh."),
        ("COT · SOT", "Restricciones de control de tensión y de sobretensión: se resuelven con máquinas que dan o absorben reactiva."),
        ("RSI · RTD · SCA · SCB · ASE…", "Códigos de tipología con los que REE identifica en el I3 la causa de cada redespacho; se muestran tal como los publica REE."),
        ("Precio capturado", "Ingreso de una tecnología dividido por su energía: lo que cobra de media por cada MWh que vende."),
        ("Techo de arbitraje", "Cota con previsión perfecta, no un ingreso: 1 MW / 4 MWh, 85 % ida y vuelta (√η al cargar y al descargar), 4 €/MWh de ciclado sobre lo descargado, ≤ 6 MWh/día."),
        ("Canibalización", "Caída del precio que cobra una tecnología porque todas producen a la vez (típico de la solar al mediodía)."),
        ("Spread capturado · TBk", "Descarga menos carga de las baterías, ponderados por energía. TBk: 4k cuartos más caros menos 4k más baratos de cada día."),
        ("Cuota renovable", "Generación renovable entre generación total peninsular (sin intercambios ni baterías; el bombeo cuenta como no renovable)."),
    ]
    y = 0.84
    yy = 0.83
    for i, (k, v) in enumerate(items):
        col = i % 2
        x0 = 0.05 + col * 0.46
        if col == 0 and i:                              # alto de la fila según la entrada más larga de las dos
            prev = items[i - 2:i]
            yy -= 0.04 + 0.023 * max(textwrap.fill(x[1], 62).count("\n") + 1 for x in prev)
        fig.text(x0, yy, k, fontsize=11, fontweight="bold", color=C["coral"])
        fig.text(x0, yy - 0.018, textwrap.fill(v, 62), fontsize=8.8, va="top", color=C["tinta"], linespacing=1.35)
    d.guardar(fig)


# ----------------------------------------------------------------- mix, baterías del sistema e histórico
COL_MIX = {"hidraulica": "#2B6F8F", "eolica": "#5F8D4E", "solar_fv": "#E9B23C", "solar_ter": "#E4572E", "term_ren": "#8FB573",
           "nuclear": "#6B4A7A", "ciclo": "#8C5A3C", "carbon": "#3B3B3B", "fuel_gas": "#9CA3AF", "cogen": "#B07AA1",
           "vapor": "#C9A27E", "turb_bombeo": "#7FA7C2"}
ORDEN_MIX = ["nuclear", "carbon", "fuel_gas", "vapor", "cogen", "ciclo", "turb_bombeo", "term_ren", "hidraulica", "eolica", "solar_ter", "solar_fv"]


def sec_mix(d, res):
    m = res.get("mix")
    if not m:
        return False
    g = m["series"]
    ks = [k for k in ORDEN_MIX if k in g.columns and g[k].fillna(0).sum() > 0]
    txt = (f"Las renovables cubrieron el {n(m['renovable_pct'], 1)} % de la generación peninsular (entre el {n(m['renovable_min'], 0)} % y el "
           f"{n(m['renovable_max'], 0)} % según el momento).")
    from .validacion import marca
    from .narrativa import frase_hueco

    rd = (res.get("qc") or {}).get("redata") or {}
    b_rd = rd.get("balance") or {}
    if b_rd.get("Generación renovable") and b_rd.get("Generación no renovable"):
        txt += f" Con el balance diario de REData, la cuota es del {n(b_rd['Generación renovable'] / (b_rd['Generación renovable'] + b_rd['Generación no renovable']) * 100, 1)} %."
    if m.get("txt_ren_dem"):
        txt += " " + m["txt_ren_dem"] + marca(res, "renovables")
    if "saldo_intercambios_gwh" in m:
        s = m["saldo_intercambios_gwh"]
        txt += f" Saldo físico con el exterior (tiempo real): {'exportación' if s < 0 else 'importación'} neta de {n(abs(s), 0)} GWh ({n(m['horas_exportando'], 0)} h exportando)"
        txt += (f"; saldo programado (REData): {n(b_rd['Saldo I. internacionales'], 0)} GWh." if "Saldo I. internacionales" in b_rd else ".")
    if m.get("hueco_txt"):
        txt += (" " + frase_hueco(m["hueco_txt"], res.get("ree_tr_ok"), "generación") + f" ({n(m['hueco_h'], 1)} h): "
                f"las energías de la semana no incluyen {'esos tramos' if ' y ' in m['hueco_txt'] else 'ese tramo'}.")
    fig = d.diapositiva(f"Mix de generación: renovables al {n(m['renovable_pct'], 0)} %", txt,
                        "Tiempo real de REE (telemedida y estimación, cada 5 min; ESIOS y, donde falta, demanda.ree.es). El balance oficial (REData) puede diferir, sobre todo en FV; las cuotas y "
                        "capturas se calculan sobre tiempo real porque es la única serie cuartohoraria. Renovable = eólica + hidráulica convencional (546 − 2079 − 2078) + FV + solar térmica + "
                        "térmica renovable, cuarto a cuarto, frente a la demanda real del mismo cuarto; sin intercambios, turbinación de bombeo ni baterías.")
    ax = d.eje(fig, caja=[0.07, 0.20, 0.56, 0.53])
    x = np.arange(len(g))
    base = np.zeros(len(g))
    for k in ks:
        v = g[k].fillna(0).values / 1000
        ax.fill_between(x, base, base + v, color=COL_MIX.get(k, C["gris"]), lw=0, label=m["nombres"].get(k, k))
        base = base + v
    dem = res["series"].get("demanda_real")
    if dem is not None and dem.notna().mean() > 0.5:
        ax.plot(x, dem.values / 1000, color=C["tinta"], lw=1.3, ls="--", label="Demanda")
    _ejes_dias(ax, g.index)
    ax.set_ylabel("GW")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=7, frameon=False, fontsize=7, columnspacing=1.0, handlelength=1.2)
    # tabla
    fig.add_artist(Rectangle((0.67, 0.13), 0.285, 0.60, color=C["panel"], transform=fig.transFigure))
    fig.text(0.685, 0.705, "Energía de la semana", fontsize=11.5, fontweight="bold", color=C["verde"])
    y = 0.665
    for k in m["gwh"].index:
        if m["gwh"][k] <= 0.05:
            continue
        fig.add_artist(Rectangle((0.687, y - 0.008), 0.009, 0.016, color=COL_MIX.get(k, C["gris"]), transform=fig.transFigure))
        fig.text(0.702, y, m["nombres"].get(k, k), fontsize=8.8, va="center")
        fig.text(0.885, y, f"{n(m['gwh'][k], 0)} GWh", fontsize=8.8, va="center", ha="right")
        fig.text(0.948, y, f"{n(m['cuota'][k], 1)} %", fontsize=8.8, va="center", ha="right", color=C["verde"] if k in m["renovables"] else C["gris"])
        y -= 0.036
    fig.text(0.685, 0.16, f"Renovable: {n(m['renovable_pct'], 1)} %", fontsize=12, fontweight="bold", color=C["musgo"])
    d.guardar(fig)
    return True


def sec_baterias(d, res):
    b = res.get("baterias")
    r3 = res.get("i3_resumen")
    if not b and not r3:
        return False
    partes = []
    if b:
        from .validacion import marca

        partes.append(f"Las baterías con medida propia publicada por REE en tiempo real cargaron {n(b['mwh_carga'], 0)} MWh y entregaron {n(b['mwh_entrega'], 0)} MWh "
                      f"(rendimiento aparente {n(b['rendimiento'], 0)} %{marca(res, 'baterias')}). Cargaron de media a {n(b['precio_carga'], 1)} €/MWh y descargaron a "
                      f"{n(b['precio_descarga'], 1)} €/MWh del diario: un spread capturado de {n(b['spread'], 1)} €/MWh. No incluye el almacenamiento hibridado tras el "
                      "contador de plantas renovables, así que no representa toda la potencia de baterías instalada.")
    fig = d.diapositiva("Qué hicieron las baterías del sistema", " ".join(partes) or None,
                        "Fuente: ESIOS (REE), almacenamiento en tiempo real (2166 carga, en neto; 2167 entrega), con los huecos completados con demanda.ree.es (consBat, bat), y, si está "
                        "publicado, I3 de REE. Precios de carga y descarga ponderados por la energía con el precio del diario: es una valoración, no la liquidación.")
    if b:
        ax = d.eje(fig, caja=[0.07, 0.14, 0.53, 0.58])
        pn = b["perfil_neto"]
        hrs = pn.index / 60
        ax.bar(hrs, pn.clip(lower=0).values, width=0.24, color=C["musgo"], label="Entrega (MW medios)")
        ax.bar(hrs, pn.clip(upper=0).values, width=0.24, color=C["coral"], label="Carga (MW medios)")
        ax.axhline(0, color=C["gris"], lw=0.8)
        ax.set_ylabel("MW (media de la semana por cuarto de hora)")
        ax.set_xticks(range(0, 24, 2))
        ax.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)])
        ax.set_xlim(0, 24)
        ax2 = ax.twinx()
        pa = res["perfil_act"]
        ax2.plot(pa.index / 60, pa.values, color=C["tinta"], lw=2, label="Precio diario (€/MWh)")
        ax2.set_ylabel("€/MWh")
        ax2.spines["top"].set_visible(False)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=3, frameon=False, fontsize=8.5)
    fig.add_artist(Rectangle((0.66, 0.14), 0.295, 0.58, color=C["panel"], transform=fig.transFigure))
    y = 0.695
    def linea(a, v, neg=False):
        nonlocal y
        fig.text(0.675, y, a, fontsize=9, color=C["gris"], va="center")
        fig.text(0.945, y, v, fontsize=9.5, fontweight="bold", va="center", ha="right", color=C["coral"] if neg else C["verde"])
        y -= 0.034
    if b:
        fig.text(0.675, y, "Medida propia en tiempo real (REE)", fontsize=11, fontweight="bold", color=C["verde"]); y -= 0.04
        linea("Energía cargada", f"{n(b['mwh_carga'], 0)} MWh")
        linea("Energía entregada", f"{n(b['mwh_entrega'], 0)} MWh")
        linea("Potencia máx. carga / entrega", f"{n(b['mw_max_carga'], 0)} / {n(b['mw_max_entrega'], 0)} MW")
        linea("Precio medio de carga", f"{n(b['precio_carga'], 1)} €/MWh")
        linea("Precio medio de descarga", f"{n(b['precio_descarga'], 1)} €/MWh")
        linea("Spread capturado", f"{n(b['spread'], 1)} €/MWh")
        linea("Valor a precio del diario", f"{n(b['ingreso_neto'], 0)} €")
        pmax = max(b["mw_max_entrega"], b["mw_max_carga"])
        if pmax > 0:
            linea("Valor por MW (pot. máx.) y día", f"{n(b['ingreso_neto'] / pmax / 7, 0)} €/MW·día")
            linea("Techo teórico 1 MW / 4 h", f"{n(res['bess_dia'], 0)} €/MW·día")
    if r3:
        y -= 0.015
        fig.text(0.675, y, "Liquidación (I3)", fontsize=11, fontweight="bold", color=C["verde"]); y -= 0.04
        g, c = r3["Almacenamiento generación"], r3["Almacenamiento consumo"]
        linea("Energía vendida (P48)", f"{n(g['p48_mwh'], 0)} MWh")
        linea("Ingreso medio por MWh vendido", f"{n(r3['precio_venta'], 1)} €/MWh")
        linea("Energía comprada (P48)", f"{n(abs(c['p48_mwh']), 0)} MWh")
        linea("Coste medio por MWh comprado", f"{n(r3['precio_compra'], 1)} €/MWh", neg=True)
        y -= 0.01
        fig.text(0.675, y, textwrap.fill("En el I3, «almacenamiento consumo» suma más energía que la que cargan las baterías en tiempo real: "
                                          "por eso no se resta compra de venta ni se da un resultado neto.", 48), fontsize=7.5, color=C["gris"], va="top")
    else:
        y -= 0.015
        fig.text(0.675, y, textwrap.fill("La liquidación por mercado (I3) se añade cuando REE la publica, entre el jueves y el viernes.", 40), fontsize=8.5, color=C["gris"], va="top")
    d.guardar(fig)
    return True


def sec_historico(d, res):
    h = res.get("historico")
    if h is None or len(h) < 6:
        return False
    h = h.sort_values("lunes").tail(60).reset_index(drop=True)
    cp = res.get("comparativa") or {}
    lect = ("Cada punto es una semana, calculada siempre con el mismo método. El techo de arbitraje sigue al spread diario más que al precio medio; "
            "la captura solar cae cuando la FV crece y los mediodías se abaratan.")
    if cp.get("ytd") and cp.get("ytd_prev"):
        lect += (f" Acumulado del año (4 h): {n(cp['ytd'] / 1000, 1)} k€/MW frente a {n(cp['ytd_prev'] / 1000, 1)} k€/MW en las mismas semanas "
                 f"del año anterior ({n((cp['ytd'] / cp['ytd_prev'] - 1) * 100, 0, True)} %).")
    fig = d.diapositiva(f"La semana en perspectiva: las últimas {len(h)} semanas", lect,
                        "Fuente: ESIOS (REE) y OMIE. Cálculo propio con datos públicos; las semanas anteriores al 1-oct-2025 tienen precio horario repetido en los cuatro cuartos.")
    x = np.arange(len(h))
    et = (h["etiqueta"].str[2:4] + "-" + h["etiqueta"].str[-3:]).tolist()
    paneles = [("Precio medio del diario (€/MWh)", [("precio_medio", C["verde"], "Precio medio")]),
               ("Techo de arbitraje (€/MW·día)", [("bess_4h", C["coral"], "4 h"), ("bess_2h", C["mostaza"], "2 h"), ("bess_1h", C["ciruela"], "1 h")]),
               ("Captura (% del precio medio)", [("ratio_fv", C["mostaza"], "Solar FV"), ("ratio_eol", C["azul"], "Eólica")]),
               ("Horas a precio ≤ 0", [("horas_neg", C["coral"], "Horas ≤ 0")])]
    for i, (tit, cols) in enumerate(paneles):
        r, c = divmod(i, 2)
        ax = d.eje(fig, caja=[0.07 + c * 0.47, 0.47 - r * 0.33, 0.40, 0.24])
        for col, color, lab in cols:
            if col in h and h[col].notna().any():
                ax.plot(x, h[col].values, color=color, lw=1.8, label=lab)
                ax.plot(x[-1], h[col].values[-1], "o", color=color, ms=6)
        if "ratio" in cols[0][0]:
            ax.axhline(100, color=C["gris"], ls="--", lw=0.8)
        ax.set_title(tit, fontsize=10, color=C["verde"], loc="left")
        paso = max(1, len(x) // 10)
        ax.set_xticks(x[::paso])
        ax.set_xticklabels(et[::paso], fontsize=7.5)
        if len(cols) > 1:
            ax.legend(frameon=False, fontsize=7.5, loc="upper left", ncol=3)
    d.guardar(fig)
    return True


def sec_multimercado(d, res):
    """Techo de arbitraje solo con el diario frente al techo usando también las subastas intradiarias,
    más los spreads top-bottom (TB1/TB2/TB4) de la semana."""
    mm, tb = res.get("multimercado"), res.get("tb") or {}
    if not mm or not mm.get("por_dia"):
        return False
    dias = sorted(mm["por_dia"])
    a = [mm["solo_diario"].get(x, np.nan) for x in dias]
    b = [mm["por_dia"][x] for x in dias]
    txt = (f"Con el mejor precio de cada cuarto de hora entre el diario y las tres subastas intradiarias (IDA1-3), la misma batería de 4 h habría podido captar "
           f"{n(mm['media'], 0)} €/MW al día, un {n(mm['uplift'], 0)} % más que solo con el diario ({n(mm['media_diario'], 0)} €/MW). Es el margen que deja la "
           f"reoptimización intradiaria: con previsión perfecta y sin límite de liquidez, así que es un techo, no un ingreso esperable.")
    fig = d.diapositiva("Arbitraje: solo diario frente a diario + intradiarios", txt,
                        "Fuente: OMIE vía ESIOS (diario e IDA1-3, 15 min). Misma programación dinámica que el techo del diario, comprando al mínimo y vendiendo al máximo de cada cuarto. "
                        "TBk = media de los 4k cuartos de hora más caros − media de los 4k más baratos de cada día (entre paréntesis, versión horaria: k horas). El año anterior, con el "
                        "mismo método (diario cuartohorario desde el 1-oct-2025; antes, horario).")
    ax = d.eje(fig, caja=[0.07, 0.18, 0.56, 0.54])
    x = np.arange(len(dias))
    ax.bar(x - 0.2, a, 0.38, color=C["verde"], label="Solo diario")
    ax.bar(x + 0.2, b, 0.38, color=C["coral"], label="Diario + IDA1-3")
    for i, (u, v) in enumerate(zip(a, b)):
        if not np.isnan(u):
            ax.text(i - 0.2, u * 1.01, n(u, 0), ha="center", fontsize=8)
        ax.text(i + 0.2, v * 1.01, n(v, 0), ha="center", fontsize=8, color=C["coral"])
    ax.set_xticks(x)
    ax.set_xticklabels([etiqueta_dia(k) for k in dias])
    ax.set_ylabel("€/MW·día (batería 1 MW / 4 MWh)")
    _leyenda(ax, 2)
    fig.add_artist(Rectangle((0.67, 0.14), 0.285, 0.58, color=C["panel"], transform=fig.transFigure))
    fig.text(0.685, 0.69, "Spreads de la semana", fontsize=11.5, fontweight="bold", color=C["verde"])
    y = 0.645
    ant = (res.get("comparativa") or {}).get("anterior") or {}
    tbh = res.get("tb_h") or {}
    for k in (1, 2, 4):
        fig.text(0.69, y, f"TB{k} (batería de {k} h)", fontsize=9.5, va="center")
        fig.text(0.94, y, f"{n(tb.get(k), 1)} ({n(tbh.get(k), 1)} h) €/MWh", fontsize=9.5, fontweight="bold", va="center", ha="right", color=C["verde"])
        y -= 0.05
    if ant.get("tb4") == ant.get("tb4"):
        fig.text(0.69, y, f"TB4 misma semana {ant.get('etiqueta', '')[:4]} ({'15 min' if str(ant.get('etiqueta', '')) >= '2025-S40' else 'horario'})", fontsize=9, va="center", color=C["gris"])
        fig.text(0.94, y, f"{n(ant.get('tb4'), 0)} €/MWh", fontsize=9.5, va="center", ha="right", color=C["gris"])
        y -= 0.05
    y -= 0.02
    fig.text(0.685, y, "Techo 4 h, media diaria", fontsize=11.5, fontweight="bold", color=C["verde"]); y -= 0.05
    for lab, v, col in (("Solo diario", mm["media_diario"], C["verde"]), ("Diario + IDA1-3", mm["media"], C["coral"])):
        fig.text(0.69, y, lab, fontsize=9.5, va="center")
        fig.text(0.94, y, f"{n(v, 0)} €/MW·día", fontsize=10, fontweight="bold", va="center", ha="right", color=col)
        y -= 0.05
    fig.text(0.69, y, "Margen de los intradiarios", fontsize=9.5, va="center")
    fig.text(0.94, y, f"{n(mm['uplift'], 1, True)} %", fontsize=10, fontweight="bold", va="center", ha="right", color=C["coral"])
    d.guardar(fig)
    return True
