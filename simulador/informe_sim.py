"""Informe del simulador: PDF (16:9) y web resumida en docs/simulador/. Determinista, sin IA.

Misma paleta que el informe semanal (copiada, no importada: el simulador no depende de src/).
"""
import json
import textwrap
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

from .datos import tramos

RAIZ = Path(__file__).resolve().parent.parent
RES = RAIZ / "data" / "simulador" / "resultados"
SAL = RAIZ / "docs" / "simulador"
W, H = 13.333, 7.5
C = dict(fondo="#F6F2EA", tinta="#1F2933", verde="#1E3D32", musgo="#5F8D4E", coral="#E4572E",
         ciruela="#6B4A7A", mostaza="#C9972B", gris="#6B7280", panel="#E9E2D3", linea="#D8D0BE",
         azul="#2B6F8F", marron="#8C5A3C")
LINEAS = {"diario_bess": ("Diario (BESS)", C["verde"]), "diario_fv": ("Diario (FV)", C["mostaza"]),
          "intradiario": ("Intradiario", C["azul"]), "afrr_banda": ("aFRR banda", C["coral"]),
          "afrr_activacion": ("aFRR activación", C["ciruela"]), "mfrr": ("mFRR", C["musgo"]),
          "reposicion": ("Reposición (continuo)", C["marron"])}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": C["linea"], "axes.labelcolor": C["gris"],
                     "xtick.color": C["gris"], "ytick.color": C["gris"], "text.color": C["tinta"]})
FUENTE = "Fuente: ESIOS (REE) y OMIE. Simulación propia (optimización con previsión perfecta diaria)."


def n(v, d=0):
    s = f"{v:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _resultados():
    out = {}
    vigentes = {f.stem for f in (Path(__file__).parent / "escenarios").glob("*.yml")}
    for carpeta in sorted(p for p in RES.iterdir() if p.is_dir() and p.name in vigentes):
        arch = tramos(carpeta)
        if not arch:
            continue
        m = pd.concat(pd.read_csv(x, index_col=0) for x in arch)
        m = m[~m.index.duplicated(keep="last")].sort_index()
        nombre = carpeta.name
        for x in tramos(carpeta, "_avisos.json"):
            nombre = json.load(open(x, encoding="utf-8")).get("escenario", nombre)
        out[carpeta.name] = (nombre, m)
    return out


class Deck:
    def __init__(self, ruta, periodo):
        self.pdf, self.periodo, self.n = PdfPages(ruta), periodo, 0

    def hoja(self, titulo, lectura=None, fuente=FUENTE):
        self.n += 1
        fig = plt.figure(figsize=(W, H), facecolor=C["fondo"])
        fig.add_artist(Rectangle((0, 0.982), 1, 0.018, color=C["verde"], transform=fig.transFigure))
        fig.add_artist(Rectangle((0.045, 0.905), 0.006, 0.05, color=C["coral"], transform=fig.transFigure))
        fig.text(0.06, 0.93, titulo, fontsize=22, fontweight="bold", color=C["verde"], va="center")
        if lectura:
            fig.add_artist(Rectangle((0.045, 0.80), 0.91, 0.085, color=C["panel"], transform=fig.transFigure))
            fig.text(0.06, 0.8425, textwrap.fill(lectura, 150), fontsize=10.5, va="center", linespacing=1.35)
        fig.text(0.045, 0.014, textwrap.fill(fuente, 150), fontsize=7, color=C["gris"], va="bottom")
        fig.text(0.955, 0.03, f"Simulador BESS · {self.periodo} · {self.n}", fontsize=7.5, color=C["gris"], ha="right")
        return fig

    def eje(self, fig, caja=(0.07, 0.17, 0.875, 0.57)):
        ax = fig.add_axes(caja)
        ax.set_facecolor("none")
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.grid(axis="y", color=C["linea"], linewidth=0.7)
        ax.set_axisbelow(True)
        return ax

    def guardar(self, fig, png=None):
        self.pdf.savefig(fig, facecolor=fig.get_facecolor())
        if png:
            fig.savefig(png, dpi=100, facecolor=fig.get_facecolor())
        plt.close(fig)


def _tabla(fig, df, caja, ancho_col=None, fs=10):
    ax = fig.add_axes(caja)
    ax.axis("off")
    t = ax.table(cellText=df.values, colLabels=list(df.columns), loc="upper left", cellLoc="right",
                 colLoc="center", colWidths=ancho_col)
    t.auto_set_font_size(False)
    t.set_fontsize(fs)
    t.scale(1, 1.45)
    for (r, c_), cel in t.get_celld().items():
        cel.set_edgecolor(C["linea"])
        if r == 0:
            cel.set_facecolor(C["verde"])
            if any("\n" in str(x) for x in df.columns):
                cel.set_height(cel.get_height() * 1.9)
            cel.get_text().set_color("white")
            cel.get_text().set_fontweight("bold")
        else:
            cel.set_facecolor("white" if r % 2 else C["panel"])
        if c_ == 0:
            cel.get_text().set_ha("left")
    return t


def barras_mensuales(dk, nombre, m, png):
    lin = [k for k in LINEAS if k in m and m[k].abs().sum() > 1]
    tot = m["total"]
    fig = dk.hoja(f"{nombre}", f"Ingreso neto por mercado y mes (€/MW). Total del periodo {n(tot.sum())} €/MW; "
                  f"media mensual {n(tot.mean())} €/MW; {n(m['ciclos_dia'].mean(), 2)} ciclos/día.")
    ax = dk.eje(fig)
    x = np.arange(len(m))
    pos, neg = np.zeros(len(m)), np.zeros(len(m))
    for k in lin:
        v = m[k].values
        ax.bar(x, np.where(v > 0, v, 0), bottom=pos, color=LINEAS[k][1], width=0.7, label=LINEAS[k][0])
        ax.bar(x, np.where(v < 0, v, 0), bottom=neg, color=LINEAS[k][1], width=0.7)
        pos += np.where(v > 0, v, 0)
        neg += np.where(v < 0, v, 0)
    ax.plot(x, tot.values, "o-", color=C["tinta"], lw=1.5, ms=4, label="Total neto")
    for xi, v in zip(x, tot.values):
        ax.text(xi, max(v, 0) + tot.abs().max() * 0.03, n(v / 1000, 1) + "k", ha="center", fontsize=8)
    ax.set_xticks(x, [str(i) for i in m.index], rotation=45 if len(m) > 12 else 0, fontsize=8)
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_ylabel("€/MW")
    ax.legend(ncol=8, fontsize=8.5, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0))
    dk.guardar(fig, png)


def validacion(dk, png):
    f = RES / "validacion_unef.csv"
    if not f.exists():
        return None
    v = pd.read_csv(f)
    alias = {"unef_a": "A", "unef_b": "B", "unef_c": "C", "modo_diario_4h": "Solo diario 4 h",
             "bess_4h_realista": "Realista 4 h", "c_techo": "C techo"}
    tab = pd.DataFrame({
        "Escenario": v["escenario"].map(lambda x: alias.get(x, x)), "Periodo": v["mes"],
        "Referencia (€/MW)": v["total UNEF"].map(n), "Simulador (€/MW)": v["total nuestro"].map(n),
        "Desviación": v["desviación total"], "": v["ok"]})
    fig = dk.hoja("Validación contra referencias públicas",
                  "Meses y años: UNEF BESS Index (mismos supuestos: 50 MW / 4 h, FV 50 MW en A y B, coste de ciclado "
                  "4 €/MWh, banda precio-aceptante, diario antes que banda; ±10 % mensual, ±15 % anual) y Modo "
                  "(solo diario, ±8 %). "
                  "ℹ = contraste informativo con Aurora (ingreso bruto, supuestos propios). Las partidas de mFRR, "
                  "reposición e intradiario no cuadran una a una: UNEF no publica su método para ellas.",
                  fuente="Fuentes: UNEF, acta del GT de Almacenamiento de 22-10-2026; Modo Energy (ME vBESS ES); "
                         "Aurora Energy Research vía Energy-Storage.News (20-11-2026); ESIOS (REE) y OMIE. Simulación propia.")
    _tabla(fig, tab, (0.07, 0.10, 0.86, 0.66), ancho_col=[0.14, 0.30, 0.16, 0.16, 0.14, 0.10], fs=9.5)
    dk.guardar(fig, png)
    return v


def dia_tipo(dk, esc, png):
    arch = tramos(RES / esc, "_cuartos.csv.gz")
    if not arch:
        return
    det = pd.read_csv(arch[-1], index_col=0, parse_dates=True)
    det.index = pd.to_datetime(det.index, utc=True)
    from .datos import leer
    loc = det.index.tz_convert("Europe/Madrid")
    dias = pd.Series(loc.normalize()).unique()
    dia = dias[-1]
    sel = loc.normalize() == dia
    d = det[sel]
    pr = leer(str(pd.Timestamp(dia).date()), str((pd.Timestamp(dia) + pd.Timedelta(days=1)).date()))
    t = d.index.tz_convert("Europe/Madrid")
    fig = dk.hoja(f"Un día de operación ({pd.Timestamp(dia).strftime('%d-%m-%Y')}, escenario {esc.replace('unef_', '').upper()})",
                  "Barras: carga (−) y descarga (+) en el diario tras el intradiario. Franja: banda aFRR ofrecida a subir y a bajar. "
                  "Línea negra: precio del diario. Línea verde: estado de carga (eje derecho).")
    ax = dk.eje(fig, caja=(0.07, 0.17, 0.80, 0.55))
    neto = d["dis"] - d["cg"] - d["cpv"]
    ax.bar(t, neto, width=0.009, color=np.where(neto >= 0, C["verde"], C["coral"]))
    ax.fill_between(t, neto, neto + d["bu"], color=C["ciruela"], alpha=0.18, step="mid", label="Banda a subir")
    ax.fill_between(t, neto, neto - d["bd"], color=C["azul"], alpha=0.18, step="mid", label="Banda a bajar")
    ax.set_ylabel("MW")
    ax2 = ax.twinx()
    ax2.plot(t, pr["da"].values, color=C["tinta"], lw=1.4, label="Precio diario")
    ax2.set_ylabel("€/MWh")
    ax3 = ax.twinx()
    ax3.spines["right"].set_position(("axes", 1.08))
    ax3.plot(t, d["e"], color=C["musgo"], lw=2, label="SoC (MWh)")
    ax3.set_ylabel("SoC (MWh)")
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=t.tz))
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    h3, l3 = ax3.get_legend_handles_labels()
    ax.legend(h1 + h2 + h3, l1 + l2 + l3, ncol=5, fontsize=8.5, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0))
    dk.guardar(fig, png)


def metodologia(dk):
    fig = dk.hoja("Metodología y supuestos")
    txt = [
        "Motor: optimización lineal entera mixta (HiGHS, código abierto) día a día, a 15 minutos, en tres etapas:",
        "  1) Diario y banda aFRR, con previsión perfecta del día. Réplica de UNEF (A, B, C): en el orden real de cierre, "
        "primero el diario (cierre 12:00 de D-1) y después la banda sobre lo que queda (ofertas hasta las 16:00 de D-1). "
        "C techo y realista: diario y banda co-optimizados (cota superior).",
        "  2) Intradiario: IDA1, IDA2 e IDA3 reoptimizan por turno los cuartos que cubren, con la banda ya fijada.",
        "  3) Tiempo real: activación aFRR = banda ofrecida × (energía activada ÷ banda asignada del sistema); mFRR con la "
        "potencia libre, solo en la dirección dominante del cuarto (la que fija el precio publicado) y con tope de profundidad "
        "de mercado; la energía activada se recompra o revende en el continuo al precio medio de las 2 h siguientes.",
        "Batería: rendimiento ida y vuelta 88 % (93,8 % en carga y en descarga), máximo 2 ciclos/día contando activaciones, "
        "SoC 0 a medianoche, el SoC debe cubrir 15 minutos de la banda ofrecida, sin degradación ni indisponibilidad.",
        "Coste de ciclado 4 €/MWh descargado (igual que UNEF) en la optimización; se informa aparte y no se resta del total.",
        "Híbridos: la FV y el BESS comparten el punto de conexión; sin carga de red, la batería solo carga de la FV. Perfil FV: "
        "generación FV peninsular real (ESIOS 1295) normalizada por su máximo móvil de 30 días (supuesto).",
        "Banda aFRR: precio en €/MW por hora; precio-aceptante en la réplica de UNEF; con tope de profundidad (fórmula pública de "
        "Modo Energy) en los escenarios «realistas». Cuartohoraria cuando el precio publicado cambia dentro de la hora.",
        "Límites: previsión perfecta (cota superior de lo capturable), sin IVPEE, peajes, GdO, restricciones técnicas, mecanismo "
        "de capacidad ni costes de O&M. Las cifras son referencias de optimización, no ingresos garantizados.",
    ]
    y = 0.84
    for linea in txt:
        partes = textwrap.wrap(linea, 165)
        for p in partes:
            fig.text(0.06, y, p, fontsize=10.5, va="top")
            y -= 0.035
        y -= 0.012
    dk.guardar(fig)


def generar():
    SAL.mkdir(parents=True, exist_ok=True)
    res = _resultados()
    if not res:
        print("Sin resultados que publicar.")
        return
    meses = sorted({mes for _, m in res.values() for mes in m.index})
    periodo = f"{meses[0]} a {meses[-1]}"
    dk = Deck(SAL / "simulador.pdf", periodo)
    fig = plt.figure(figsize=(W, H), facecolor=C["verde"])
    fig.text(0.07, 0.62, "Simulador de escenarios BESS", fontsize=40, fontweight="bold", color="white")
    fig.text(0.07, 0.52, "Radar del mercado eléctrico · península", fontsize=18, color=C["panel"])
    fig.text(0.07, 0.40, f"Periodo simulado: {periodo}", fontsize=14, color="white")
    fig.text(0.07, 0.35, f"Generado el {date.today().strftime('%d-%m-%Y')} con datos públicos de ESIOS (REE) y OMIE",
             fontsize=11, color=C["panel"])
    dk.pdf.savefig(fig, facecolor=fig.get_facecolor())
    plt.close(fig)
    dk.n += 1
    filas = []
    for clave, (nombre, m) in res.items():
        dias = sum(pd.Period(x).days_in_month for x in m.index)
        filas.append([nombre, n(m["total"].sum()), n(m["total"].sum() / dias * 365), n(m["ciclos_dia"].mean(), 2),
                      n(m["apuntamiento"].mean(), 0)])
    tab = pd.DataFrame(filas, columns=["Escenario", "Total periodo\n(€/MW)", "Anualizado\n(€/MW·año)", "Ciclos/día",
                                       "Precio medio\ndescarga (€/MWh)"])
    fig = dk.hoja("Resumen por escenario", f"Ingreso neto de mercado por MW (POI en híbridos, BESS en stand-alone), {periodo}.")
    _tabla(fig, tab, (0.06, 0.25, 0.88, 0.5), ancho_col=[0.44, 0.14, 0.15, 0.11, 0.16], fs=10.5)
    dk.guardar(fig, SAL / "resumen.png")
    imgs = []
    for clave, (nombre, m) in res.items():
        png = SAL / f"{clave}.png"
        barras_mensuales(dk, nombre, m, png)
        imgs.append((nombre, png.name))
    val = validacion(dk, SAL / "validacion.png")
    esc_dia = "unef_c" if "unef_c" in res else next(iter(res))
    dia_tipo(dk, esc_dia, SAL / "dia.png")
    metodologia(dk)
    dk.pdf.close()
    # web
    filas_html = "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td></tr>" for r in filas)
    figs = "".join(f'<h2>{nm}</h2><img src="{im}" alt="{nm}">' for nm, im in imgs)
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Simulador de escenarios BESS</title><style>
body{{font-family:system-ui,sans-serif;background:{C['fondo']};color:{C['tinta']};max-width:1100px;margin:auto;padding:1.5rem}}
h1{{color:{C['verde']}}}h2{{color:{C['verde']};margin-top:2rem}}table{{border-collapse:collapse;width:100%;background:white}}
td,th{{border:1px solid {C['linea']};padding:.4rem .6rem;text-align:right}}td:first-child,th:first-child{{text-align:left}}
th{{background:{C['verde']};color:white}}img{{width:100%;border:1px solid {C['linea']}}}
.btn{{display:inline-block;background:{C['coral']};color:white;padding:.6rem 1rem;border-radius:6px;text-decoration:none}}
</style></head><body><h1>Simulador de escenarios BESS</h1>
<p>Ingreso neto de mercado de baterías en la península, {periodo}. Optimización con datos públicos de ESIOS (REE) y OMIE.</p>
<p><a class="btn" href="simulador.pdf">Informe completo (PDF)</a> · <a href="../index.html">Radar semanal</a></p>
<table><tr><th>Escenario</th><th>Total periodo (€/MW)</th><th>Anualizado (€/MW·año)</th><th>Ciclos/día</th><th>Precio medio de descarga (€/MWh)</th></tr>{filas_html}</table>
{figs}<h2>Validación contra el UNEF BESS Index</h2><img src="validacion.png" alt="Validación">
<h2>Un día de operación</h2><img src="dia.png" alt="Día tipo">
<p style="font-size:.8rem;color:{C['gris']}">Previsión perfecta: cota superior de lo capturable. No incluye IVPEE, peajes, GdO, restricciones técnicas ni O&amp;M.
Fuente: ESIOS (REE) y OMIE. Elaboración propia.</p></body></html>"""
    (SAL / "index.html").write_text(html, encoding="utf-8")
    print(f"Informe del simulador: {dk.n} páginas en {SAL}")


if __name__ == "__main__":
    generar()
