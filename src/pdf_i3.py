"""Diapositivas basadas en el I3 de REE: sector por tecnología, cascada de programas,
restricciones técnicas y seguimiento de la operación reforzada."""
import textwrap

import numpy as np
import pandas as pd
from matplotlib.patches import Circle, Polygon, Rectangle

from .i3 import cascada
from .narrativa import n
from .pdf import C, PALETA, Deck

MERCADOS = ["Diario", "Intradiario 1", "Intradiario 2", "Intradiario 3", "Continuo", "Restricciones MD", "Restricciones TR", "Terciaria"]
COL_MERC = {"Bilaterales": C["verde"], "Diario": C["coral"], "Intradiario 1": C["mostaza"], "Intradiario 2": C["ciruela"],
            "Intradiario 3": C["musgo"], "Continuo": C["azul"], "Restricciones MD": C["marron"], "Restricciones TR": C["gris"], "Terciaria": "#B07AA1"}
TEC_CLAVE = [("Solar fotovoltaica", "Solar FV"), ("Almacenamiento generación", "Almac. gen."), ("Almacenamiento consumo", "Almac. cons."), ("Eólica", "Eólica")]
FUENTE_I3 = "Fuente: I3 de REE (vía ESIOS), {rango}. Agregado por tecnología: el I3 no baja a unidad de programación."


def eur(v, d=0):
    return f"{n(v, d)} €"


def _tabla(d, fig, cols, filas, xs, al, y0=0.72, alto=0.044, total_ultima=False, fs=9.5, x0=0.045, ancho=0.91):
    tope = x0 + ancho - 0.005
    fig.add_artist(Rectangle((x0, y0 + 0.002), ancho, 0.045, color=C["verde"], transform=fig.transFigure))
    for x, c, a in zip(xs, cols, al):
        fig.text(min(x + 0.12, tope) if a == "right" else x, y0 + 0.0245, c, color="white", fontsize=fs, fontweight="bold", va="center", ha=a)
    for i, fila in enumerate(filas):
        y = y0 - 0.025 - i * alto
        ultima = total_ultima and i == len(filas) - 1
        if ultima:
            fig.add_artist(Rectangle((x0, y - alto / 2), ancho, alto, color="#CFE3C8", transform=fig.transFigure))
        elif i % 2 == 0:
            fig.add_artist(Rectangle((x0, y - alto / 2), ancho, alto, color=C["panel"], transform=fig.transFigure))
        for x, v, a in zip(xs, fila, al):
            fig.text(min(x + 0.12, tope) if a == "right" else x, y, str(v), fontsize=fs, va="center", ha=a, fontweight="bold" if ultima else "normal")


# ------------------------------------------------------------------ SECCIÓN 02 · sector
def precio_capturado(d, i3, rango):
    e = i3.groupby(["tecnologia", "mercado", "magnitud"])["valor"].sum().unstack("magnitud").fillna(0)
    pbf = i3[(i3["mercado"] == "PBF") & (i3["magnitud"] == "energia")].groupby("tecnologia")["valor"].sum().abs().sort_values(ascending=False)
    tecs = list(pbf.index[:13])
    for t_ in ("Almacenamiento generación", "Almacenamiento consumo"):   # informe con foco BESS: siempre visibles
        if t_ in pbf.index and t_ not in tecs:
            tecs.append(t_)
    bruto = i3[i3["magnitud"] == "energia"].groupby(["tecnologia", "mercado"])["valor"].apply(lambda x: x.abs().sum())
    fig = d.diapositiva("Precio capturado por tecnología y mercado",
                        "Lo que cada tecnología cobra de media en cada mercado. Sale del I3, que llega a los cuatro días: hace falta la energía y el ingreso "
                        "mercado a mercado, y el panel en vivo no lo da. Donde la compra y la venta casi se cancelan no se muestra precio.",
                        FUENTE_I3.format(rango=rango))
    # tabla de calor: una fila por tecnología y una columna por mercado (antes, barras horizontales
    # de 8 colores por tecnología que no se podían leer)
    M = np.full((len(tecs), len(MERCADOS)), np.nan)
    for i_, t in enumerate(tecs):
        for j_, m in enumerate(MERCADOS):
            if (t, m) not in e.index:
                continue
            en = e.loc[(t, m), "energia"] if "energia" in e.columns else 0
            ing = e.loc[(t, m), "ingreso"] if "ingreso" in e.columns else 0
            if abs(en) < 100 or abs(en) < 0.35 * float(bruto.get((t, m), 0)) or ing == 0:
                continue
            p = ing / en
            if abs(p) <= 900:
                M[i_, j_] = p
    from matplotlib.colors import TwoSlopeNorm

    ref = np.nanmedian(M[:, 0]) if np.isfinite(M[:, 0]).any() else np.nanmedian(M)
    ref = ref if np.isfinite(ref) else 100.0
    lo, hi = np.nanmin(M) if np.isfinite(M).any() else 0, np.nanmax(M) if np.isfinite(M).any() else 1
    norm = TwoSlopeNorm(vcenter=ref, vmin=min(lo, ref - 1), vmax=max(hi, ref + 1))
    ax = fig.add_axes([0.21, 0.10, 0.74, 0.64])
    cmap = __import__("matplotlib").colormaps["RdYlGn"].copy()
    cmap.set_bad(C["fondo"])
    ax.imshow(np.ma.masked_invalid(M), aspect="auto", cmap=cmap, norm=norm, alpha=0.75)
    for i_ in range(M.shape[0]):
        for j_ in range(M.shape[1]):
            v = M[i_, j_]
            ax.text(j_, i_, "·" if np.isnan(v) else n(v, 0), ha="center", va="center", fontsize=8.5,
                    color=C["gris"] if np.isnan(v) else C["tinta"], fontweight="bold" if tecs[i_].startswith("Almacenamiento") else None)
    ax.set_xticks(range(len(MERCADOS)))
    ax.set_xticklabels([m.replace("Intradiario ", "ID").replace("Restricciones ", "Restr. ") for m in MERCADOS], fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(tecs)))
    ax.set_yticklabels(tecs, fontsize=9)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(MERCADOS)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(tecs)), minor=True)
    ax.grid(which="minor", color=C["fondo"], linewidth=2)
    ax.tick_params(which="both", length=0)
    fig.text(0.21, 0.07, textwrap.fill(f"€/MWh. Verde: por encima de la mediana del diario ({n(ref, 0)} €/MWh); rojo: por debajo. «·» = sin energía suficiente o compra y venta "
             "casi canceladas. En consumo (bombeo, almacenamiento) la cifra es lo que pagó por MWh.", 160), fontsize=7.5, color=C["gris"], va="top")
    d.guardar(fig)


def ingreso_tabla(d, i3, rango):
    ing = i3[i3["magnitud"] == "ingreso"].groupby(["mercado", "tecnologia"])["valor"].sum()
    filas = []
    tot_col = {k: 0.0 for k, _ in TEC_CLAVE}
    tot_all = 0.0
    for m in MERCADOS:
        v = [float(ing.get((m, t), np.nan)) for t, _ in TEC_CLAVE]
        total = float(ing[ing.index.get_level_values(0) == m].sum()) if m in ing.index.get_level_values(0) else np.nan
        filas.append([m.replace("Intradiario ", "Intradiario ")] + ["—" if np.isnan(x) else eur(x) for x in v] + ["—" if np.isnan(total) else eur(total)])
        for (t, _), x in zip(TEC_CLAVE, v):
            tot_col[t] += 0 if np.isnan(x) else x
        tot_all += 0 if np.isnan(total) else total
    filas.append(["TOTAL"] + [eur(tot_col[t]) for t, _ in TEC_CLAVE] + [eur(tot_all)])
    fig = d.diapositiva("Ingreso total por mercado y tecnología",
                        "Lo que cada tecnología ha cobrado, o pagado, en cada mercado a lo largo de todo el periodo. La compra es negativa, así que un importe "
                        "negativo es un coste; una celda vacía es un concepto que REE no valora, no un cero.",
                        FUENTE_I3.format(rango=rango) + " El ingreso de mercados distintos sí se suma (son euros); la energía no.")
    _tabla(d, fig, ["Mercado"] + [x for _, x in TEC_CLAVE] + ["Todas las tec."], filas, [0.06, 0.26, 0.40, 0.54, 0.68, 0.82], ["left", "right", "right", "right", "right", "right"],
           y0=0.715, alto=0.052, total_ultima=True, fs=10)
    d.guardar(fig)
    return tot_all


def ingreso_dos_escalas(d, i3, rango):
    ing = i3[i3["magnitud"] == "ingreso"].groupby(["mercado", "tecnologia"])["valor"].sum()
    fig = d.diapositiva("Ingreso total por mercado · las dos escalas",
                        "El mismo cruce, en gráfico. Va en dos ejes porque solar y eólica mueven tres órdenes de magnitud más que el almacenamiento: "
                        "juntos en el mismo eje, el almacenamiento quedaría pegado al cero.", FUENTE_I3.format(rango=rango))
    for k, (grupo, tit, cols) in enumerate((([("Solar fotovoltaica", "Solar FV"), ("Eólica", "Eólica")], "Solar fotovoltaica y eólica (M€)", [C["verde"], C["coral"]]),
                                            ([("Almacenamiento generación", "Almac. gen."), ("Almacenamiento consumo", "Almac. cons.")], "Almacenamiento (miles de €)", [C["verde"], C["coral"]]))):
        ax = d.eje(fig, caja=[0.07 + k * 0.48, 0.17, 0.41, 0.54])
        esc = 1e6 if k == 0 else 1e3
        x = np.arange(len(MERCADOS))
        for g, ((t, lab), col) in enumerate(zip(grupo, cols)):
            vals = [float(ing.get((m, t), 0.0)) / esc for m in MERCADOS]
            ax.bar(x + (g - 0.5) * 0.38, vals, 0.36, color=col, label=lab)
        ax.axhline(0, color=C["gris"], lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels([m.replace("Restricciones", "Restr.").replace("Intradiario", "ID") for m in MERCADOS], rotation=35, ha="right", fontsize=8)
        ax.set_title(tit, fontsize=10.5, color=C["verde"], loc="left")
        ax.legend(frameon=False, fontsize=8.5)
    d.guardar(fig)


def tecnologia_detalle(d, i3, tec, nombre, dias, rango):
    sub = i3[i3["tecnologia"] == tec]
    mercs = ["Bilaterales"] + MERCADOS
    fig = d.diapositiva(f"{nombre} · energía e ingreso por mercado",
                        "A la izquierda, la energía que mueve en cada mercado; a la derecha, lo que cobra en cada uno. El P48 queda fuera: es el programa físico, no un mercado.",
                        FUENTE_I3.format(rango=rango) + " Series agregadas por día.")
    for k, (mag, tit, esc, uni) in enumerate((("energia", "Energía (MWh)", 1, "MWh"), ("ingreso", "Ingreso (€)", 1, "€"))):
        ax = d.eje(fig, caja=[0.07 + k * 0.48, 0.2, 0.41, 0.51])
        pos = np.zeros(len(dias))
        neg = np.zeros(len(dias))
        for m in mercs:
            if mag == "ingreso" and m == "Bilaterales":
                continue
            s = sub[(sub["mercado"] == m) & (sub["magnitud"] == mag)].groupby("fecha")["valor"].sum().reindex(dias).fillna(0).values
            base = np.where(s >= 0, pos, neg)
            ax.bar(range(len(dias)), s, 0.62, bottom=base, color=COL_MERC[m], label=m)
            pos += np.where(s >= 0, s, 0)
            neg += np.where(s < 0, s, 0)
        ax.axhline(0, color=C["gris"], lw=0.8)
        ax.set_xticks(range(len(dias)))
        ax.set_xticklabels([x.strftime("%d-%m") for x in dias], fontsize=8)
        ax.set_title(tit, fontsize=10.5, color=C["verde"], loc="left")
        if k == 0:
            ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(1.12, -0.12), frameon=False, fontsize=8)
    d.guardar(fig)
    # precio capturado
    e = sub.groupby(["mercado", "magnitud"])["valor"].sum().unstack("magnitud").fillna(0)
    bruto = sub[sub["magnitud"] == "energia"].groupby("mercado")["valor"].apply(lambda x: x.abs().sum())
    fig = d.diapositiva(f"{nombre} · precio capturado",
                        "Lo cobrado en cada mercado entre su propia energía. Cuando la compra y la venta de un mercado casi se cancelan, el cociente se dispara y deja "
                        "de ser un precio: esos casos no se pintan.", FUENTE_I3.format(rango=rango))
    ax = d.eje(fig)
    xs, vs, cs = [], [], []
    for m in MERCADOS:
        en = abs(e.loc[m].get("energia", 0)) if m in e.index else 0
        # mismo criterio que la tabla de calor: si la energía neta es menos del 35 % de la bruta, compra y venta
        # casi se cancelan y el cociente deja de ser un precio (p. ej. eólica en IDA3: −133 €/MWh)
        if m in e.index and en > 100 and "ingreso" in e.columns and en >= 0.35 * float(bruto.get(m, 0)):
            p = e.loc[m, "ingreso"] / e.loc[m, "energia"]
            if abs(p) < 900:
                xs.append(m)
                vs.append(p)
                cs.append(COL_MERC[m])
    bars = ax.bar(range(len(xs)), vs, 0.5, color=cs)
    for b, v in zip(bars, vs):
        ax.text(b.get_x() + b.get_width() / 2, v + (4 if v >= 0 else -10), n(v, 1), ha="center", fontsize=9.5, fontweight="bold")
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_xticks(range(len(xs)))
    ax.set_xticklabels(xs, fontsize=9)
    ax.set_xlim(-0.7, max(len(xs), 6) - 0.3)
    ax.margins(y=0.18)
    ax.set_ylabel("€/MWh")
    d.guardar(fig)


# ------------------------------------------------------------------ SECCIÓN 03 · restricciones
def _cinta(ax, x0, x1, ya0, yb0, ya1, yb1, color, alpha=1.0):
    t = np.linspace(0, 1, 40)
    s = t * t * (3 - 2 * t)
    xs = x0 + (x1 - x0) * t
    top = ya0 + (ya1 - ya0) * s
    bot = yb0 + (yb1 - yb0) * s
    ax.add_patch(Polygon(np.r_[np.c_[xs, top], np.c_[xs[::-1], bot[::-1]]], closed=True, facecolor=color, edgecolor="none", alpha=alpha))


def sankey(d, i3, tec, titulo, lectura, rango):
    c = cascada(i3, tec)
    fig = d.diapositiva(titulo, lectura,
                        FUENTE_I3.format(rango=rango) + f" La cascada cierra en el P48 publicado ({n(c['p48'], 0)} MWh) con un {n(c['dif_pct'], 2)} % de diferencia. "
                        "Las restricciones van abiertas en subir y bajar, no en neto. Aquí la fase II sí cuenta: es parte de la cadena de programas.")
    ax = fig.add_axes([0.03, 0.10, 0.94, 0.68])
    ax.axis("off")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    vmax = max(abs(c["pbf"]), abs(c["p48"]), 1.0)
    esc = 26.0 / vmax                      # unidades de eje por MWh (el flujo más grande ocupa 30)
    cy = 52.0
    nodos = [("PBF", c["pbf"], 36), ("PDVP · viable", c["pbf"] + c["restr_pbf_sub"] + c["restr_pbf_baj"], 50),
             ("PHF · horario final", None, 64), ("Tras tiempo real", None, 78), ("P48", c["p48"], 92)]
    v = [nodos[0][1], nodos[1][1]]
    v.append(v[1] + c["ida_sub"] + c["ida_baj"])
    v.append(v[2] + c["restr_tr_sub"] + c["restr_tr_baj"])
    v.append(v[3] + c["terc_sub"] + c["terc_baj"])
    pub = [c["pbf"], c["pdvp"] or v[1], c["phf"] or v[2], None, c["p48"]]
    xs = [36, 50, 64, 78, 92]
    gris = "#C9CDD1"
    # entradas
    base = max(abs(c["diario"]) + abs(c["bilaterales"]), 1e-9)
    hD, hB = abs(c["diario"]) / base * v[0] * esc, abs(c["bilaterales"]) / base * v[0] * esc
    top0, bot0 = cy + v[0] * esc / 2, cy - v[0] * esc / 2
    _cinta(ax, 16, xs[0], top0, top0 - hD, top0, top0 - hD, C["verde"])
    _cinta(ax, 16, xs[0], top0 - hD, bot0, top0 - hD, bot0, C["azul"])
    ax.text(15, top0 - hD / 2, f"Mercado diario\n{n(c['diario'], 0)} MWh", ha="right", va="center", fontsize=8.5, fontweight="bold")
    ax.text(15, bot0 + hB / 2, f"Bilaterales\n{n(c['bilaterales'], 0)} MWh", ha="right", va="center", fontsize=8.5, fontweight="bold")
    # tramos principales
    for k in range(4):
        h0, h1 = v[k] * esc, v[k + 1] * esc
        _cinta(ax, xs[k], xs[k + 1], cy + h0 / 2, cy - h0 / 2, cy + h1 / 2, cy - h1 / 2, gris)
    _cinta(ax, xs[3], 98, cy + v[4] * esc / 2, cy - v[4] * esc / 2, cy + v[4] * esc / 2, cy - v[4] * esc / 2, gris)
    for k in range(5):
        h = v[k] * esc
        ax.add_patch(Rectangle((xs[k] - 0.5, cy - h / 2), 1.0, h, color=C["tinta"] if k == 4 else "#7A8087"))
        val = pub[k] if pub[k] else v[k]
        ax.text(xs[k], cy + h / 2 + 3, f"{nodos[k][0]}\n{n(val, 0)} MWh", ha="center", va="bottom", fontsize=8, fontweight="bold")
    # ramas: subir (entra por arriba al nodo siguiente) / bajar (sale por abajo del nodo actual)
    ramas = [(0, c["restr_pbf_sub"], c["restr_pbf_baj"], "Restricciones técnicas · PBF"), (1, c["ida_sub"], c["ida_baj"], "Intradiarios"),
             (2, c["restr_tr_sub"], c["restr_tr_baj"], "Restricciones · tiempo real"), (3, c["terc_sub"], c["terc_baj"], "Balance (terciaria)")]
    for k, up, down, nombre in ramas:
        wu, wd = abs(up) * esc, abs(down) * esc
        hk, hk1 = v[k] * esc, v[k + 1] * esc
        if wu > 0:
            top = cy + hk1 / 2
            _cinta(ax, xs[k] + 1, xs[k + 1], top + 14, top + 14 - max(wu, 0.25), top, top - max(wu, 0.25), "#3E9E5B", 0.9)
            ax.text(xs[k] + 7, top + 15.5, f"{nombre}\na subir · +{n(up, 0)} MWh", ha="center", va="bottom", fontsize=7, color="#2F7F47", fontweight="bold")
        if wd > 0:
            bot = cy - hk / 2
            _cinta(ax, xs[k], xs[k] + 13, bot + max(wd, 0.25), bot, bot - 14 + max(wd, 0.25), bot - 14, "#C0392B", 0.9)
            ax.text(xs[k] + 7.5, bot - 16, f"{nombre}\na bajar · −{n(abs(down), 0)} MWh", ha="center", va="top", fontsize=7, color="#A93226", fontweight="bold")
    d.guardar(fig)
    return c


def programa_dia(d, i3, tec, nombre, dias, rango):
    sub = i3[(i3["tecnologia"] == tec) & (i3["magnitud"] == "energia")]
    pbf = sub[sub["mercado"] == "PBF"].groupby("fecha")["valor"].sum().reindex(dias).fillna(0)
    fa1 = sub[(sub["mercado"] == "Restricciones MD") & (sub["fase"] == "MD · Fase I") & (sub["sentido"] == "Bajar")].groupby("fecha")["valor"].sum().reindex(dias).fillna(0)
    tr = sub[(sub["mercado"] == "Restricciones TR") & (sub["sentido"] == "Bajar")].groupby("fecha")["valor"].sum().reindex(dias).fillna(0)
    fig = d.diapositiva(f"{nombre} · programa y recorte, día a día",
                        "A la izquierda, el programa y lo que se le baja, en la misma escala. A la derecha, ese recorte en porcentaje del PBF, que es donde se aprecia "
                        "el detalle y donde los periodos se comparan entre sí aunque el programa cambie de tamaño.", FUENTE_I3.format(rango=rango))
    ax = d.eje(fig, caja=[0.07, 0.15, 0.41, 0.56])
    x = np.arange(len(dias))
    ax.bar(x - 0.27, pbf.values, 0.26, color="#9CA3AF", label="Programa PBF")
    ax.bar(x, fa1.values, 0.26, color=C["verde"], label="MD · Fase I")
    ax.bar(x + 0.27, tr.values, 0.26, color=C["mostaza"], label="Tiempo real")
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([q.strftime("%d-%m") for q in dias], fontsize=8)
    ax.set_title("Energía (MWh)", fontsize=10.5, color=C["verde"], loc="left")
    ax.legend(ncol=3, frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    ax2 = d.eje(fig, caja=[0.56, 0.15, 0.39, 0.56])
    pf = fa1.abs() / pbf.replace(0, np.nan) * 100
    pt = tr.abs() / pbf.replace(0, np.nan) * 100
    ax2.bar(x, pf.fillna(0).values, 0.62, color=C["verde"], label="MD · Fase I")
    ax2.bar(x, pt.fillna(0).values, 0.62, bottom=pf.fillna(0).values, color=C["mostaza"], label="Tiempo real")
    ax2.set_xticks(x)
    ax2.set_xticklabels([q.strftime("%d-%m") for q in dias], fontsize=8)
    ax2.set_title("Recorte (% del PBF)", fontsize=10.5, color=C["verde"], loc="left")
    ax2.legend(ncol=2, frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    d.guardar(fig)
    return float((fa1.sum() + tr.sum()) / pbf.sum() * 100) if pbf.sum() else np.nan


def tabla_recorte(d, i3, rango):
    e = i3[i3["magnitud"] == "energia"]
    pbf = e[e["mercado"] == "PBF"].groupby("tecnologia")["valor"].sum().sort_values(ascending=False)
    fa1 = e[(e["mercado"] == "Restricciones MD") & (e["fase"] == "MD · Fase I") & (e["sentido"] == "Bajar")].groupby("tecnologia")["valor"].sum()
    tr = e[(e["mercado"] == "Restricciones TR") & (e["sentido"] == "Bajar")].groupby("tecnologia")["valor"].sum()
    filas = []
    for t in pbf.index[:16]:
        a, b = float(fa1.get(t, 0)), float(tr.get(t, 0))
        tot = a + b
        pct = "—" if (pbf[t] <= 0 or tot == 0) else f"{n(abs(tot) / pbf[t] * 100, 1)} %"
        filas.append([t, n(pbf[t], 0), n(a, 0) if a else "—", n(b, 0) if b else "—", n(tot, 0) if tot else "—", pct])
    fig = d.diapositiva("Recorte por restricciones sobre el programa (PBF)",
                        "El PBF es el programa que sale del mercado diario y los bilaterales, antes de que se resuelvan las restricciones. A su lado, la energía que estas le "
                        "mandan bajar en la fase I y en tiempo real, y lo que ese recorte pesa sobre el programa.",
                        FUENTE_I3.format(rango=rango) + " Se mide contra el PBF y no contra el P48 porque el P48 es lo que queda después de recortar, y dividir entre él infla el porcentaje. La fase II queda fuera.")
    _tabla(d, fig, ["Tecnología", "Programa PBF (MWh)", "MD · Fase I (MWh)", "Tiempo real (MWh)", "Total bajado (MWh)", "% del PBF"], filas,
           [0.06, 0.37, 0.50, 0.63, 0.76, 0.88], ["left", "right", "right", "right", "right", "right"], y0=0.72, alto=0.0345, fs=8.8)
    d.guardar(fig)


def fase_tipologia(d, i3, dias, rango):
    r = i3[i3["mercado"].isin(["Restricciones MD", "Restricciones TR"])].copy()
    r["clave"] = np.where(r["mercado"] == "Restricciones TR", "Tiempo real", r["fase"]) + " · " + r["tipologia"].replace("", "otras")
    for k, (mag, tit, uni) in enumerate((("energia", "Energía por fase y tipología, día a día", "MWh"), ("ingreso", "Coste por fase y tipología, día a día", "€"))):
        x = r[r["magnitud"] == mag]
        tot = x.groupby("clave")["valor"].apply(lambda s: s.abs().sum()).sort_values(ascending=False)
        claves = list(tot.index[:12])
        fig = d.diapositiva(tit, "La fase I resuelve el problema de red; la fase II es el reequilibrio que devuelve el sistema al balance y cancela la energía de la fase I. "
                            "La tipología es el problema que motivó el redespacho: COT y SOT son tensión.", FUENTE_I3.format(rango=rango) + " Las combinaciones de menor peso se agrupan en «otras».")
        ax = d.eje(fig, caja=[0.07, 0.25, 0.875, 0.46])
        pos = np.zeros(len(dias))
        neg = np.zeros(len(dias))
        for i, cl in enumerate(claves + ["otras combinaciones"]):
            if cl == "otras combinaciones":
                s = x[~x["clave"].isin(claves)].groupby("fecha")["valor"].sum().reindex(dias).fillna(0).values
            else:
                s = x[x["clave"] == cl].groupby("fecha")["valor"].sum().reindex(dias).fillna(0).values
            base = np.where(s >= 0, pos, neg)
            ax.bar(range(len(dias)), s, 0.62, bottom=base, color=PALETA[i % len(PALETA)] if i < 8 else plt_gris(i), label=cl)
            pos += np.where(s >= 0, s, 0)
            neg += np.where(s < 0, s, 0)
        ax.axhline(0, color=C["gris"], lw=0.8)
        ax.set_xticks(range(len(dias)))
        ax.set_xticklabels([q.strftime("%Y-%m-%d") for q in dias], fontsize=8.5)
        ax.set_ylabel(uni)
        ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.1), frameon=False, fontsize=7.5)
        d.guardar(fig)


def plt_gris(i):
    return ["#9CA3AF", "#B6BCC4", "#CDD2D8", "#8895A3", "#A4B0BC"][i % 5]


def tabla_fases(d, i3, rango):
    r = i3[i3["mercado"].isin(["Restricciones MD", "Restricciones TR"])]
    r = r.assign(fase2=np.where(r["mercado"] == "Restricciones TR", "Tiempo real", r["fase"]))
    g = r.groupby(["fase2", "tipologia", "sentido", "magnitud"])["valor"].sum().unstack("magnitud").fillna(0).reset_index()
    if "ingreso" not in g.columns or "energia" not in g.columns:
        return
    g = g[g["energia"].abs() > 0].sort_values("ingreso", ascending=False)
    filas = []
    for _, x in g.head(14).iterrows():
        filas.append([x["fase2"].replace("MD · ", "MD · "), x["tipologia"] or "—", x["sentido"] or "—", n(x["energia"], 0), eur(x["ingreso"]), n(x["ingreso"] / x["energia"], 1) if x["energia"] else "—"])
    fig = d.diapositiva("Totales por fase, tipología y sentido", None,
                        FUENTE_I3.format(rango=rango) + f" Se muestran las 14 de mayor ingreso, de {len(g)} combinaciones. En restricciones el precio publicado no se abre por tipo: el €/MWh de COT y SOT de una misma fila es el mismo.")
    _tabla(d, fig, ["Fase", "Tipología", "Sentido", "Energía (MWh)", "Ingreso", "€/MWh"], filas, [0.06, 0.30, 0.43, 0.55, 0.70, 0.86], ["left", "left", "left", "right", "right", "right"],
           y0=0.80, alto=0.047, fs=9.5)
    d.guardar(fig)


def reparto_tecnologia(d, i3, rango):
    r = i3[(i3["mercado"].isin(["Restricciones MD", "Restricciones TR"])) & (i3["magnitud"] == "ingreso")]
    tot = r.groupby("tecnologia")["valor"].apply(lambda s: s.abs().sum()).sort_values(ascending=False).head(12)
    tips = list(r.groupby("tipologia")["valor"].apply(lambda s: s.abs().sum()).sort_values(ascending=False).index[:9])
    fig = d.diapositiva("Reparto por tecnología", "Quién presta el servicio: qué tecnologías se redespachan y por qué causa.", FUENTE_I3.format(rango=rango))
    ax = d.eje(fig, caja=[0.2, 0.2, 0.74, 0.52])
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=C["linea"], lw=0.7)
    tecs = list(tot.index)
    pos = np.zeros(len(tecs))
    neg = np.zeros(len(tecs))
    for i, tp in enumerate(tips):
        s = np.array([r[(r["tecnologia"] == t) & (r["tipologia"] == tp)]["valor"].sum() for t in tecs]) / 1e6
        base = np.where(s >= 0, pos, neg)
        ax.barh(range(len(tecs)), s, left=base, color=PALETA[i % len(PALETA)], label=tp or "N/A", height=0.65)
        pos += np.where(s >= 0, s, 0)
        neg += np.where(s < 0, s, 0)
    ax.set_yticks(range(len(tecs)))
    ax.set_yticklabels(tecs, fontsize=9)
    ax.invert_yaxis()
    ax.axvline(0, color=C["gris"], lw=0.8)
    ax.set_xlabel("M€")
    ax.legend(ncol=9, loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False, fontsize=8)
    d.guardar(fig)


def cot_sot_dia(d, i3, dias, rango):
    r = i3[(i3["mercado"] == "Restricciones MD") & (i3["fase"] == "MD · Fase I") & (i3["sentido"] == "Subir") & (i3["tipologia"].isin(["COT", "SOT"]))]
    ing = r[r["magnitud"] == "ingreso"].groupby("fecha")["valor"].sum().reindex(dias).fillna(0)
    act = r[r["magnitud"] == "energia_x_spot"].groupby("fecha")["valor"].sum().reindex(dias).fillna(0)
    rea = (ing - act).clip(lower=0)
    fig = d.diapositiva("Ingreso de COT y SOT día a día, separando activa y reactiva",
                        "Lo que se cobra por encima del precio del mercado diario de cada hora es lo que el sistema paga por el servicio de tensión. Con α = 45° la tangente vale 1, "
                        "así que los MVArh son los MWh y el €/MVArh es la prima sin más.", FUENTE_I3.format(rango=rango))
    ax = d.eje(fig)
    x = np.arange(len(dias))
    ax.bar(x, act.values / 1e6, 0.62, color=C["azul"], label="Energía activa (a precio spot)")
    ax.bar(x, rea.values / 1e6, 0.62, bottom=act.values / 1e6, color=C["mostaza"], label="Energía reactiva (prima sobre el spot)")
    ax.set_xticks(x)
    ax.set_xticklabels([q.strftime("%Y-%m-%d") for q in dias], fontsize=9)
    ax.set_ylabel("M€")
    ax.legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.1), frameon=False)
    d.guardar(fig)


# ------------------------------------------------------------------ operación reforzada
def operacion_reforzada(d, hist, rango_hist, corte="2025-04-27"):  # víspera del apagón del 28-abr-2025
    """hist: tabla I3 completa desde 2025-01-01. Devuelve diccionario con cifras clave."""
    h = hist[(hist["mercado"] == "Restricciones MD") & (hist["fase"] == "MD · Fase I") & (hist["sentido"] == "Subir") & (hist["magnitud"] == "ingreso") & (hist["tipologia"].isin(["COT", "SOT"]))]
    if len(h) == 0:
        return None
    dia = h.groupby(["fecha", "tipologia"])["valor"].sum().unstack("tipologia").fillna(0)
    for t in ("COT", "SOT"):
        if t not in dia:
            dia[t] = 0.0
    dia["tot"] = dia["COT"] + dia["SOT"]
    pre = dia[dia.index <= pd.Timestamp(corte)]
    base_dia = float(pre["tot"].mean()) if len(pre) else float(dia["tot"].mean())
    base_cot, base_sot = (float(pre["COT"].mean()), float(pre["SOT"].mean())) if len(pre) else (0.0, 0.0)
    dia["anio"] = dia.index.year
    por_anio = dia.groupby("anio").agg(dias=("tot", "count"), COT=("COT", "sum"), SOT=("SOT", "sum"), total=("tot", "sum"))
    por_anio["base"] = por_anio["dias"] * base_dia
    por_anio["sobre"] = por_anio["total"] - por_anio["base"]
    ult = dia.index.max()
    parcial = {a: (a == ult.year and ult < pd.Timestamp(f"{a}-12-31")) for a in por_anio.index}
    marca = lambda a: f"{a}*" if parcial[a] else str(a)
    # ---- portada de bloque
    fig = d.diapositiva("Seguimiento de la Operación Reforzada", None, f"Fuente: I3 de REE, {rango_hist}. COT y SOT a subir, fase I del mercado diario. *Año incompleto: el último con dato llega al {ult.date()}.")
    fig.text(0.06, 0.82, "Las dos restricciones de tensión que la sostienen: qué son y cuánto cuestan", fontsize=14, color=C["gris"], fontweight="bold")
    from matplotlib.patches import FancyBboxPatch

    def caja(x, y, w, h_, col):
        fig.add_artist(FancyBboxPatch((x, y), w, h_, boxstyle="round,pad=0.004,rounding_size=0.02", transform=fig.transFigure, facecolor=col, edgecolor=C["mostaza"] if col == C["panel"] else "none", lw=1.2))
    caja(0.05, 0.56, 0.44, 0.20, C["panel"])
    fig.text(0.07, 0.73, "COT · Control de tensión", fontsize=13, fontweight="bold", color=C["musgo"])
    fig.text(0.07, 0.705, textwrap.fill("La tensión de un nudo se sale de su margen y el operador arranca máquinas para corregirla. No se llaman por su energía: se llaman porque pueden dar o absorber reactiva, que es lo que mueve la tensión. La activa que producen es un efecto secundario, y es la que se paga.", 70), fontsize=8.8, va="top", linespacing=1.4)
    caja(0.51, 0.56, 0.44, 0.20, C["panel"])
    fig.text(0.53, 0.73, "SOT · Sobretensión", fontsize=13, fontweight="bold", color=C["coral"])
    fig.text(0.53, 0.705, textwrap.fill("El caso concreto en el que la tensión se va por arriba, típicamente con poca demanda y mucha red en vacío. Se resuelve absorbiendo reactiva. Sigue por detrás del COT, también en el último año.", 70), fontsize=8.8, va="top", linespacing=1.4)
    a1, a2 = por_anio.index[0], por_anio.index[-1]
    cards = [(0.05, C["verde"], "COT · CONTROL DE TENSIÓN", [(marca(a), f"{n(por_anio.loc[a, 'COT'] / 1e6, 0)} M€") for a in (a1, a2) if a in por_anio.index]),
             (0.365, C["indigo"] if "indigo" in C else "#1F2933", "SOT · SOBRETENSIÓN", [(marca(a), f"{n(por_anio.loc[a, 'SOT'] / 1e6, 0)} M€") for a in (a1, a2) if a in por_anio.index])]
    for x, col, tit, vals in cards:
        caja(x, 0.35, 0.29, 0.16, col)
        fig.text(x + 0.02, 0.485, tit, fontsize=8.5, color="white")
        for i, (a, v) in enumerate(vals):
            fig.text(x + 0.02, 0.44 - i * 0.045, f"{a}   {v}", fontsize=14, fontweight="bold", color="#FFD27A")
    cc = h[h["fecha"].dt.year == a1].groupby("tecnologia")["valor"].sum()
    pct = cc / cc.sum() * 100 if cc.sum() else cc
    caja(0.68, 0.35, 0.27, 0.16, C["panel"])
    fig.text(0.695, 0.485, f"QUIÉN LO COBRA · {a1}", fontsize=8.5, color=C["gris"])
    lid = pct.sort_values(ascending=False)
    if len(lid):
        fig.text(0.695, 0.44, f"{lid.index[0]}   {n(lid.iloc[0], 1)} %", fontsize=12.5, fontweight="bold", color=C["musgo"])
        fig.text(0.695, 0.395, f"Resto   {n(100 - lid.iloc[0], 1)} %", fontsize=12.5, fontweight="bold", color=C["musgo"])
    caja(0.05, 0.12, 0.90, 0.19, "#1F2933")
    fig.text(0.07, 0.275, textwrap.fill("Las dos son problemas de red que hoy solo resuelven máquinas síncronas. Por eso el control de tensión con electrónica de potencia (P.O. 7.4) no es una mejora técnica menor: "
                                        f"es lo que abriría estos {n(por_anio.loc[a1, 'total'] / 1e6, 0)} M€ de {a1} a algo más que el ciclo combinado.", 125), fontsize=11, color="white", va="top", linespacing=1.5)
    d.guardar(fig)
    # ---- acumulado
    fig = d.diapositiva("La operación reforzada se paga con gas",
                        f"Coste base más sobrecoste: la media diaria de COT y SOT del {dia.index.min().date()} al {corte} (víspera del apagón) son {n(base_dia, 0)} € al día. "
                        "Multiplicada por los días de cada año da el coste base; lo que hay por encima es el sobrecoste de la operación reforzada.",
                        f"Fuente: I3 de REE, {rango_hist}. COT y SOT a subir, fase I del mercado diario. *Año incompleto.")
    fig.add_artist(Rectangle((0.045, 0.60), 0.28, 0.065, color=C["verde"], transform=fig.transFigure))
    fig.add_artist(Rectangle((0.34, 0.60), 0.30, 0.065, color=C["panel"], transform=fig.transFigure))
    fig.add_artist(Rectangle((0.655, 0.60), 0.30, 0.065, color="#1F2933", transform=fig.transFigure))
    for x, tit, col, key in ((0.055, "COSTE BASE", "white", "base"), (0.35, "SOBRECOSTE OP. REFORZADA", C["tinta"], "sobre"), (0.665, "TOTAL COT + SOT", "white", "total")):
        fig.text(x, 0.645, tit, fontsize=7.5, color=col)
        fig.text(x, 0.612, "   ".join(f"{marca(a)} {n(por_anio.loc[a, key] / 1e6, 0)} M€" for a in por_anio.index), fontsize=10.5, fontweight="bold", color="#FFD27A" if key == "total" else (C["azul"] if key == "sobre" else "white"))
    ax = d.eje(fig, caja=[0.08, 0.12, 0.86, 0.43])
    cum_c, cum_s = dia["COT"].cumsum() / 1e6, (dia["COT"] + dia["SOT"]).cumsum() / 1e6
    ax.fill_between(dia.index, 0, cum_s, color=C["mostaza"], alpha=0.55, label="SOT (€) acumulado")
    ax.fill_between(dia.index, 0, cum_c, color=C["azul"], alpha=0.6, label="COT (€) acumulado")
    ref = np.arange(1, len(dia) + 1) * base_dia / 1e6
    ax.plot(dia.index, ref, color=C["gris"], ls="--", lw=1.4, label="Referencia anterior al apagón (COT+SOT)")
    ax.set_ylabel("M€")
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.1), frameon=False, fontsize=8.5)
    d.guardar(fig)
    # ---- año a año
    fig = d.diapositiva("El coste del control de tensión, año a año",
                        "El denominador del coste base son los días con dato, no los del calendario: el 29 de abril de 2025 no tiene fase I (es el día siguiente al apagón) y con 365 días la referencia saldría inflada.",
                        f"Fuente: I3 de REE, {rango_hist}. *Año incompleto: el último con dato llega al {ult.date()}.")
    filas = [[marca(a), int(r_["dias"]), eur(r_["COT"]), eur(r_["SOT"]), eur(r_["total"]), eur(r_["base"]), eur(r_["sobre"])] for a, r_ in por_anio.iterrows()]
    _tabla(d, fig, ["Año", "Días con dato", "COT", "SOT", "Total", "Coste base", "Sobrecoste"], filas, [0.06, 0.20, 0.33, 0.47, 0.61, 0.75, 0.88], ["left"] + ["right"] * 6, y0=0.72, alto=0.06, fs=9.5)
    d.guardar(fig)
    # ---- mes a mes
    m = dia[["COT", "SOT"]].copy()
    m["mes"] = m.index.to_period("M").astype(str)
    mm = m.groupby("mes")[["COT", "SOT"]].sum() / 1e6
    fig = d.diapositiva("El sobrecoste, mes a mes",
                        f"El salto está en {corte[:4]}-{int(corte[5:7]) + 1:02d}, el mes siguiente al apagón. Para situarlo: a la media diaria anterior, un mes de treinta días costaba {n(base_dia * 30, 0)} €.",
                        f"Fuente: I3 de REE, {rango_hist}.")
    ax = d.eje(fig, caja=[0.08, 0.2, 0.87, 0.50])
    ax.bar(range(len(mm)), mm["COT"], 0.7, color=C["coral"], label="COT")
    ax.bar(range(len(mm)), mm["SOT"], 0.7, bottom=mm["COT"], color=C["mostaza"], label="SOT")
    ax.axhline(base_dia * 30 / 1e6, color=C["gris"], ls="--", lw=1.2)
    ax.set_xticks(range(len(mm)))
    ax.set_xticklabels(mm.index, rotation=60, ha="right", fontsize=7.5)
    ax.set_ylabel("M€")
    ax.legend(ncol=2, frameon=False, loc="upper left")
    d.guardar(fig)
    # ---- quién cobra
    a = a1
    q = h[h["fecha"].dt.year == a].groupby("tecnologia")["valor"].sum().sort_values(ascending=False)
    fig = d.diapositiva(f"Quién cobra el control de tensión ({a})",
                        "El reparto se lee de un año completo. Mezclar un año entero con medio daría una cuota que no es de ninguno de los dos, y este es justo el número que se cita fuera de contexto.",
                        f"Fuente: I3 de REE, {rango_hist}. Las dos son problemas de red que hoy solo resuelven máquinas síncronas.")
    ax = d.eje(fig, caja=[0.16, 0.14, 0.40, 0.50])
    ax.grid(axis="y", visible=False)
    ax.barh(range(len(q)), q.values / 1e6, color=C["azul"], height=0.5)
    ax.set_yticks(range(len(q)))
    ax.set_yticklabels(q.index, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("M€")
    filas = [[t, eur(v), f"{n(v / q.sum() * 100, 1)} %"] for t, v in q.items()]
    _tabla(d, fig, ["Tecnología", "Ingreso", "%"], filas, [0.63, 0.73, 0.85], ["left", "right", "right"], y0=0.66, alto=0.045, fs=9, x0=0.62, ancho=0.335)
    d.guardar(fig)
    return {"base_dia": base_dia, "por_anio": por_anio}
