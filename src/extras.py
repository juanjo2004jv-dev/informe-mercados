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
    return pd.DataFrame({"arbitraje": arb, "banda": banda}).dropna()


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
    cs = res["captura"].get("gen_solar_fv")
    if cs:
        r = cs["ratio"]
        est = (ROJO, "Canibalización alta") if r < 70 else (AMBAR, "Canibalización moderada") if r < 85 else (VERDE, "Captura sana")
        fil.append(("Promotor solar FV", est, f"Captura {n(r, 0)} % del precio medio. Regla: <70 % rojo, 70-85 % ámbar, >85 % verde."))
    else:
        fil.append(("Promotor solar FV", (C["gris"], "Sin dato"), "Falta la serie de generación solar (ver config.yml)."))
    b, p = res["bess_dia"], np.nanmean([x["bess_dia"] for x in res["semanas"][:-1]])
    v = (b / p - 1) * 100 if p else np.nan
    est = (VERDE, "Techo al alza") if v > 10 else (ROJO, "Techo a la baja") if v < -10 else (AMBAR, "Techo estable")
    fil.append(("Almacenamiento (arbitraje)", est, f"{n(b, 0)} €/MW·día, {n(v, 1, True)} % frente a la media de 4 semanas. Regla: ±10 %."))
    sp = res["spread_medio"]
    est = (VERDE, "Spread amplio") if sp > 120 else (AMBAR, "Spread medio") if sp > 60 else (ROJO, "Spread estrecho")
    fil.append(("Volatilidad intradía", est, f"Spread diario medio {n(sp, 0)} €/MWh. Regla: >120 verde, 60-120 ámbar, <60 rojo."))
    pr = bd.get("prima_afrr")
    if pr is not None:
        est = (VERDE, "Prima de balance alta") if pr > 25 else (AMBAR, "Prima moderada") if pr > 8 else (ROJO, "Prima baja")
        fil.append(("Servicios de balance", est, f"aFRR a subir paga {n(pr, 1, True)} €/MWh sobre el diario ({bd.get('prima_afrr_tipo', '')}). Regla: >25 verde, 8-25 ámbar."))
    d = res["demanda"]
    if d and "mape" in d:
        est = (VERDE, "Previsión precisa") if d["mape"] < 1.5 else (AMBAR, "Desvíos moderados") if d["mape"] < 3 else (ROJO, "Desvíos altos")
        fil.append(("Calidad de previsión", est, f"Error medio de la previsión de demanda {n(d['mape'], 2)} %. Regla: <1,5 % verde."))
    hn = res["horas_neg"]
    est = (ROJO, "Muchas horas ≤ 0") if hn > 15 else (AMBAR, "Horas ≤ 0 presentes") if hn > 3 else (VERDE, "Pocas horas ≤ 0")
    fil.append(("Precios cero y negativos", est, f"{n(hn, 1)} h a precio ≤ 0. Bueno para cargar, malo para vender sin almacenamiento."))
    return fil


def resumen_extras(res, cfg):
    bd = {}
    s = res["series"].get("afrr_subir")
    if s is not None and s.notna().mean() > 0.3:
        bd["prima_afrr"] = float((s - res["spot"]).mean())
        bd["prima_afrr_tipo"] = "media simple de los cuartos de hora"
        act = res["series"].get("afrr_energia_act_subir")
        if act is not None and act.notna().mean() > 0.3:
            m = s.notna() & res["spot"].notna() & act.notna() & (act > 0)
            if m.sum() and act[m].sum() > 0:
                # lo que importa a quien presta el servicio es el precio cuando le activan:
                # se pondera por la energía activada a subir (ID 680)
                bd["prima_afrr"] = float(((s - res["spot"])[m] * act[m]).sum() / act[m].sum())
                bd["prima_afrr_tipo"] = "ponderada por la energía activada a subir"
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
                        "Fuente: ESIOS (REE) y OMIE. La banda se aproxima como Σ(precio a subir + precio a bajar) × 0,25 h por cuarto de hora, sin activación ni penalizaciones. Aproximación, no liquidación.")
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
        ("RSI · RTD · SCA · SCB", "Otras tipologías de restricción técnica del I3 (seguridad, red, solución por activación y compensación)."),
        ("Precio capturado", "Ingreso de una tecnología dividido por su energía: lo que cobra de media por cada MWh que vende."),
        ("Techo de arbitraje", "Ingreso máximo teórico de una batería con previsión perfecta de precios del diario. No es un ingreso real."),
        ("Canibalización", "Caída del precio que cobra una tecnología porque todas producen a la vez (típico de la solar al mediodía)."),
    ]
    y = 0.84
    for i, (k, v) in enumerate(items):
        col = i % 2
        row = i // 2
        x0 = 0.05 + col * 0.46
        yy = 0.82 - row * 0.12
        fig.text(x0, yy, k, fontsize=11, fontweight="bold", color=C["coral"])
        fig.text(x0, yy - 0.018, textwrap.fill(v, 62), fontsize=8.8, va="top", color=C["tinta"], linespacing=1.35)
    d.guardar(fig)
