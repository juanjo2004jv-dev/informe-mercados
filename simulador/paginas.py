"""Páginas del PDF del simulador con la estructura del UNEF BESS Index (escenarios, ficha trimestral por escenario y
evolución desde 2025 con apuntamiento y ciclos), con marca y paleta propias. Determinista, sin IA.
"""
import textwrap

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

from .informe_sim import C, LINEAS, RES, W, H, _tabla, n

ALIAS = {"unef_a": "A", "unef_b": "B", "unef_c": "C", "c_operable": "C op.", "bess_4h_realista": "R",
         "c_techo": "C+", "modo_diario_4h": "D"}
PRINCIPALES = ["unef_a", "unef_b", "unef_c", "c_operable", "bess_4h_realista"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def mes_txt(p):
    p = pd.Period(str(p), freq="M")
    return f"{MESES[p.month - 1]} {p.year}"


def cfg_escenario(clave):
    from .run import escenario
    return escenario(clave)


def _mw_norm(cfg):
    a = cfg["activo"]
    return a["p_poi_mw"] if cfg["normalizar_por"] == "poi" else a["p_bess_mw"]


def mercados_txt(cfg):
    m, a = cfg["mercados"], cfg["activo"]
    out = ["Mercado diario"]
    if m.get("intradiario", True):
        out.append("Intradiario (IDA1-3)")
    if m.get("continuo", False):
        out.append("Continuo (MIC)")
    if m.get("afrr_banda", True):
        out.append("aFRR (banda y activación)")
    if m.get("mfrr", True):
        out.append("mFRR (activación)")
    if a.get("fv_mwp", 0) and cfg.get("gdo", {}).get("activa", False):
        out.append("Garantías de origen")
    out.append("CON carga de red" if a.get("carga_desde_red", True) else "SIN carga de red")
    return out


def config_txt(cfg):
    a = cfg["activo"]
    h = a["e_bess_mwh"] / a["p_bess_mw"]
    bess = f"{n(a['p_bess_mw'])} MW ({n(h)} h)"
    if a.get("fv_mwp", 0):
        return f"{n(a['fv_mwp'] / a.get('fv_ratio_dc_ac', 1.0))} MW FV + {bess}"
    return bess


def decision_txt(cfg):
    imp = cfg.get("prevision", {}).get("modo", "perfecta") == "imperfecta"
    sec = cfg["mercados"].get("banda_secuencial", False)
    a = "Sin conocer los precios del día (previsión)" if imp else "Previsión perfecta del día"
    return a + ("; diario antes que banda" if sec else "; diario y banda co-optimizados")


def separador(dk, num, titulo, sub=""):
    dk.n += 1
    fig = plt.figure(figsize=(W, H), facecolor=C["fondo"])
    fig.add_artist(Rectangle((0, 0), 0.42, 1, color=C["verde"], transform=fig.transFigure))
    fig.text(0.06, 0.56, "SECCIÓN", fontsize=14, color=C["panel"])
    fig.text(0.06, 0.38, f"{num:02d}", fontsize=80, fontweight="bold", color="white")
    fig.text(0.47, 0.52, textwrap.fill(titulo, 30), fontsize=30, fontweight="bold", color=C["verde"], va="center")
    if sub:
        fig.text(0.47, 0.38, textwrap.fill(sub, 60), fontsize=12, color=C["gris"], va="top")
    fig.add_artist(Rectangle((0.42, 0), 0.58, 0.012, color=C["coral"], transform=fig.transFigure))
    dk.pdf.savefig(fig, facecolor=fig.get_facecolor())
    plt.close(fig)


def escenarios(dk, claves, png=None):
    """Página «Escenarios a considerar»: configuración, mercados y forma de decidir de cada escenario."""
    cfgs = [(k, cfg_escenario(k)) for k in claves]
    k0 = cfgs[0][1]
    notas = [
        f"Coste de ciclado de {n(k0['mercados']['coste_ciclado_eur_mwh'])} €/MWh en la optimización (diferencial mínimo "
        "entre mercados, igual que UNEF); se informa aparte y no se resta del total.",
        "Híbridos (A y B): ingreso neto dividido por la potencia del punto de conexión (50 MW). Stand-alone: por la "
        "potencia del BESS.",
        "Garantías de origen en los híbridos desde ene-2026 (volumen según la CNMC, precio de las subastas de OMIP).",
        "A, B y C replican el UNEF BESS Index (previsión perfecta). C operable y realista deciden sin conocer los "
        "precios del día, con las activaciones limitadas por el estado de carga.",
    ]
    fig = dk.hoja("Escenarios a considerar")
    y = 0.86
    for t in notas:
        fig.text(0.06, y, "▪ " + textwrap.fill(t, 175), fontsize=9.5, va="top", linespacing=1.3)
        y -= 0.04 * (1 + len(t) // 175)
    ncol = len(cfgs)
    ancho = 0.88 / ncol
    for i, (k, cfg) in enumerate(cfgs):
        x0 = 0.06 + i * ancho
        w = ancho - 0.015
        tipo = "FV + BESS" if cfg["activo"].get("fv_mwp", 0) else "BESS stand-alone"
        fig.text(x0 + w / 2, 0.665, f"{ALIAS.get(k, k)} · {tipo}", ha="center", fontsize=10, color=C["verde"],
                 fontweight="bold")
        fig.add_artist(FancyBboxPatch((x0, 0.535), w, 0.105, boxstyle="round,pad=0.004", color=C["verde"],
                                      transform=fig.transFigure))
        fig.text(x0 + w / 2, 0.5875, textwrap.fill(config_txt(cfg), 18), ha="center", va="center", fontsize=13,
                 fontweight="bold", color="white")
        yy = 0.50
        for mt in mercados_txt(cfg):
            fig.add_artist(FancyBboxPatch((x0 + 0.01, yy - 0.035), w - 0.02, 0.038, boxstyle="round,pad=0.002",
                                          facecolor="white", edgecolor=C["linea"], transform=fig.transFigure))
            fig.text(x0 + w / 2, yy - 0.016, mt, ha="center", va="center", fontsize=8.6,
                     color=C["coral"] if "carga" in mt else C["tinta"])
            yy -= 0.045
        fig.text(x0 + w / 2, yy - 0.01, textwrap.fill(decision_txt(cfg), 30), ha="center", va="top", fontsize=8,
                 color=C["gris"], style="italic")
    dk.guardar(fig, png)


def _trimestre(m):
    """Últimos 3 meses completos (si no los hay, los últimos que existan)."""
    comp = m[m["dias"] >= pd.PeriodIndex(m.index, freq="M").days_in_month]
    sel = comp.iloc[-3:] if len(comp) >= 3 else m.iloc[-3:]
    return sel


def _apunt(sel):
    p = sel["ciclos_dia"] * sel["dias"]
    return float((sel["apuntamiento"] * p).sum() / p.sum()) if p.sum() else float("nan")


def _unef(clave):
    try:
        ref = yaml.safe_load(open(RES.parent.parent.parent / "simulador" / "valores_dorados.yml", encoding="utf-8"))
        return ref.get("unef", {}).get(clave, {})
    except (OSError, ValueError, AttributeError):
        return {}


def ficha(dk, clave, nombre, m, png=None):
    """Ficha trimestral de un escenario (como las de UNEF): resumen financiero en € y apuntamiento, tabla de €/MW por
    mercado y barras apiladas por mes; además, el contraste con UNEF cuando hay referencia publicada."""
    cfg = cfg_escenario(clave)
    mw = _mw_norm(cfg)
    sel = _trimestre(m)
    lin = [k for k in LINEAS if k in sel and sel[k].abs().sum() > 1]
    fig = dk.hoja(f"Escenario {ALIAS.get(clave, '')} · {config_txt(cfg)} · {mes_txt(sel.index[0])} a {mes_txt(sel.index[-1])}",
                  f"{nombre}. Mercados: {', '.join(mercados_txt(cfg))}. {decision_txt(cfg)}. Ingreso por MW de "
                  f"{'punto de conexión' if cfg['normalizar_por'] == 'poi' else 'BESS'} ({n(mw)} MW).")
    fig.add_artist(Circle((0.025, 0.93), 0.016, color=C["coral"], transform=fig.transFigure))
    fig.text(0.025, 0.93, ALIAS.get(clave, "")[:2].strip(), ha="center", va="center", fontsize=10, fontweight="bold",
             color="white")
    # Resumen financiero
    ref = _unef(clave)
    filas = [["Ingresos netos del trimestre", n(sel["total"].sum() * mw) + " €"]]
    for mes, r in sel.iterrows():
        filas.append([f"   {mes_txt(mes)}", n(r["total"] * mw) + " €"])
    filas.append(["Apuntamiento del activo", n(_apunt(sel)) + " €/MWh"])
    for mes, r in sel.iterrows():
        u = ref.get(str(mes), {}) if ref else {}
        extra = f"  (UNEF {n(u['apuntamiento'])})" if "apuntamiento" in u else ""
        filas.append([f"   {mes_txt(mes)}", n(r["apuntamiento"]) + " €/MWh" + extra])
    filas.append(["Ciclos diarios medios", n(float((sel["ciclos_dia"] * sel["dias"]).sum() / sel["dias"].sum()), 2)])
    tab = pd.DataFrame(filas, columns=["Resumen financiero", ""])
    t = _tabla(fig, tab, (0.03, 0.10, 0.35, 0.66), ancho_col=[0.52, 0.48], fs=9.5)
    for (r, c_), cel in t.get_celld().items():
        if r > 0 and not str(tab.iloc[r - 1, 0]).startswith("   "):
            cel.get_text().set_fontweight("bold")
    # Tabla €/MW por mercado (y, debajo de cada mes, las partidas publicadas por UNEF cuando las hay)
    mapa_unef = {"gdo": "gdo_derivado"}
    cab = ["Mes"] + [LINEAS[k][0].replace(" (", "\n(").replace("aFRR ", "aFRR\n") for k in lin] + ["Total\n(€/MW)"]
    filas = []
    for mes, r in sel.iterrows():
        filas.append([mes_txt(mes)] + [n(r[k]) for k in lin] + [n(r["total"])])
        u = ref.get(str(mes)) if ref else None
        if u:
            filas.append(["   UNEF"] + [n(u[mapa_unef.get(k, k)]) if mapa_unef.get(k, k) in u else "—" for k in lin]
                         + [n(u["total"])])
    t2 = pd.DataFrame(filas, columns=cab)
    nc = len(t2.columns)
    alto = 0.035 * (len(t2) + 1.6)
    tb = _tabla(fig, t2, (0.40, 0.77 - alto, 0.57, alto), ancho_col=[0.11] + [0.89 / (nc - 1)] * (nc - 1), fs=7.6)
    for (r, c_), cel in tb.get_celld().items():
        if r > 0 and str(t2.iloc[r - 1, 0]).startswith("   "):
            cel.set_facecolor("#F3E3DC")
            cel.get_text().set_color(C["gris"])
    if ref:
        desv = [f"{mes_txt(x)} {sel.loc[x, 'total'] / ref[str(x)]['total'] - 1:+.1%}".replace(".", ",")
                for x in sel.index if str(x) in ref]
        if desv:
            fig.text(0.40, 0.765 - alto - 0.02, "Desviación del total frente a UNEF: " + " · ".join(desv),
                     fontsize=8.5, color=C["coral"], va="top")
    # Barras apiladas por mes
    ax = dk.eje(fig, caja=(0.44, 0.10, 0.52, 0.30))
    x = np.arange(len(sel))
    pos, neg = np.zeros(len(sel)), np.zeros(len(sel))
    for k in lin:
        v = sel[k].values
        ax.bar(x, np.where(v > 0, v, 0), bottom=pos, color=LINEAS[k][1], width=0.55, label=LINEAS[k][0])
        ax.bar(x, np.where(v < 0, v, 0), bottom=neg, color=LINEAS[k][1], width=0.55)
        pos += np.where(v > 0, v, 0)
        neg += np.where(v < 0, v, 0)
    for xi, v, p in zip(x, sel["total"].values, pos):
        ax.text(xi, p + pos.max() * 0.04, f"{n(v)} €/MW", ha="center", fontsize=9, fontweight="bold", color=C["verde"],
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=C["coral"]))
    ax.set_ylim(min(neg.min() * 1.15, 0), pos.max() * 1.25)
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_xticks(x, [mes_txt(i) for i in sel.index], fontsize=9)
    ax.set_ylabel("€/MW", fontsize=9)
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(ncol=4, fontsize=7.2, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0))
    dk.guardar(fig, png)


def historico(dk, clave, nombre, m, png=None):
    """Evolución mensual desde el inicio (ingresos por mercado, total anual y apuntamiento con ciclos diarios)."""
    cfg = cfg_escenario(clave)
    lin = [k for k in LINEAS if k in m and m[k].abs().sum() > 1]
    anios = pd.PeriodIndex(m.index, freq="M").year
    tot = m.groupby(anios)["total"].sum()
    comp = m.groupby(anios)["dias"].sum()
    txt = " · ".join(f"{a}: {n(v)} €/MW" + ("" if comp[a] >= 365 else f" ({n(comp[a])} días)") for a, v in tot.items())
    fig = dk.hoja(f"Escenario {ALIAS.get(clave, '')} · {config_txt(cfg)} · evolución desde {mes_txt(m.index[0])}",
                  f"{nombre}. Ingreso neto por mercado y mes (€/MW) y, debajo, apuntamiento del activo (precio medio del "
                  f"diario en la descarga) y ciclos diarios medios. {txt}.")
    ax = dk.eje(fig, caja=(0.07, 0.47, 0.88, 0.28))
    x = np.arange(len(m))
    pos, neg = np.zeros(len(m)), np.zeros(len(m))
    for k in lin:
        v = m[k].values
        ax.bar(x, np.where(v > 0, v, 0), bottom=pos, color=LINEAS[k][1], width=0.7, label=LINEAS[k][0])
        ax.bar(x, np.where(v < 0, v, 0), bottom=neg, color=LINEAS[k][1], width=0.7)
        pos += np.where(v > 0, v, 0)
        neg += np.where(v < 0, v, 0)
    ax.plot(x, m["total"].values, "o", color=C["tinta"], ms=3, label="Total neto")
    for a in tot.index[1:]:
        i0 = int(np.argmax(anios == a))
        ax.axvline(i0 - 0.5, color=C["coral"], lw=2)
    for a, v in tot.items():
        idx = np.where(anios == a)[0]
        ax.text(idx.mean(), pos.max() * 1.08, f"{a}: {n(v)} €/MW", ha="center", fontsize=9, fontweight="bold",
                color=C["verde"], bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=C["coral"]))
    ax.set_ylim(min(neg.min() * 1.2, 0), pos.max() * 1.3)
    ax.set_xticks(x, [str(i) for i in m.index], rotation=60, fontsize=7)
    ax.set_ylabel("€/MW", fontsize=9)
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(ncol=9, fontsize=7.5, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0))
    ax2 = dk.eje(fig, caja=(0.07, 0.10, 0.88, 0.27))
    ax2.bar(x, m["apuntamiento"].values, color=C["mostaza"], width=0.6, label="Apuntamiento del activo (€/MWh)")
    ax2.set_ylabel("€/MWh", fontsize=9)
    ax2.set_xticks(x, [str(i) for i in m.index], rotation=60, fontsize=7)
    ax2.tick_params(axis="y", labelsize=8)
    ax3 = ax2.twinx()
    ax3.plot(x, m["ciclos_dia"].values, "o-", color=C["verde"], lw=1.6, ms=3.5, label="Ciclos diarios medios")
    ax3.set_ylim(0, max(2.2, m["ciclos_dia"].max() * 1.15))
    ax3.set_ylabel("Ciclos/día", fontsize=9)
    ax3.tick_params(axis="y", labelsize=8)
    for a in tot.index[1:]:
        ax2.axvline(int(np.argmax(anios == a)) - 0.5, color=C["coral"], lw=2)
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax3.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, ncol=2, fontsize=8, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0))
    dk.guardar(fig, png)


def comparativa(dk, res, png=None):
    """Comparativa del último trimestre entre escenarios: €/MW por mercado (lo que UNEF reparte en tres fichas)."""
    claves = [k for k in PRINCIPALES + ["c_techo", "modo_diario_4h"] if k in res]
    if not claves:
        return
    filas = []
    for k in claves:
        sel = _trimestre(res[k][1])
        fila = {"Escenario": textwrap.fill(f"{ALIAS.get(k, k)} · {res[k][0].split('·', 1)[-1].strip()}", 34)}
        for c, (lab, _) in LINEAS.items():
            fila[lab.replace(" (", "\n(").replace("aFRR ", "aFRR\n")] = n(sel[c].sum()) if c in sel else "—"
        fila["Total\ntrimestre"] = n(sel["total"].sum())
        fila["Apunt.\n€/MWh"] = n(_apunt(sel))
        filas.append(fila)
    t = pd.DataFrame(filas)
    t = t.loc[:, [c for c in t.columns if not (t[c] == "—").all() and not (t[c] == "0").all()]]
    per = f"{mes_txt(_trimestre(res[claves[0]][1]).index[0])} a {mes_txt(_trimestre(res[claves[0]][1]).index[-1])}"
    fig = dk.hoja(f"Comparativa del trimestre ({per}), €/MW",
                  "Suma del trimestre por mercado. La diferencia entre C techo, C y C operable mide el valor de conocer el "
                  "futuro y del orden real de los mercados; entre C operable y realista, el de la profundidad de mercado.")
    nc = len(t.columns)
    tb = _tabla(fig, t, (0.04, 0.16, 0.92, 0.58), ancho_col=[0.25] + [0.75 / (nc - 1)] * (nc - 1), fs=8.4)
    for (r, c_), cel in tb.get_celld().items():
        if r > 0:
            cel.set_height(cel.get_height() * 1.5)
    dk.guardar(fig, png)
