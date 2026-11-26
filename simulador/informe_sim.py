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
          "intradiario": ("Intradiario (IDA)", C["azul"]), "continuo": ("Continuo (MIC)", "#7FB3C8"),
          "afrr_banda": ("aFRR banda", C["coral"]),
          "afrr_activacion": ("aFRR activación", C["ciruela"]), "mfrr": ("mFRR", C["musgo"]),
          "reposicion": ("Reposición (continuo)", C["marron"])}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": C["linea"], "axes.labelcolor": C["gris"],
                     "xtick.color": C["gris"], "ytick.color": C["gris"], "text.color": C["tinta"]})
FUENTE = "Fuente: ESIOS (REE) y OMIE. Simulación propia (optimización día a día; ver supuestos de cada escenario)."


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
             "bess_4h_realista": "Realista 4 h", "c_techo": "C techo", "c_operable": "C operable"}
    tab = pd.DataFrame({
        "Escenario": v["escenario"].map(lambda x: alias.get(x, x)), "Periodo": v["mes"],
        "Referencia (€/MW)": v["total UNEF"].map(n), "Simulador (€/MW)": v["total nuestro"].map(n),
        "Desviación": v["desviación total"], "": v["ok"]})
    fig = dk.hoja("Validación contra referencias públicas",
                  "Meses y años: UNEF BESS Index (mismos supuestos: 50 MW / 4 h, FV 50 MW en A y B, coste de ciclado "
                  "4 €/MWh, banda precio-aceptante, diario antes que banda; ±10 % mensual, ±15 % anual) y Modo "
                  "(solo diario, ±8 %). "
                  "ℹ = informativo: Aurora (ingreso bruto, supuestos propios) y captura de «C operable» (sin conocer "
                  "los precios del día) frente a su techo; Modo usa un 80 % como factor de captura por defecto.",
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


ALIAS = {"unef_a": "A", "unef_b": "B", "unef_c": "C", "modo_diario_4h": "Solo diario 4 h",
         "bess_4h_realista": "Realista 4 h", "c_techo": "C techo", "c_operable": "C operable"}
FUENTE_FIN = ("Fuentes: ACER, encuesta de recursos 2030 (PC-2026-E-04): CAPEX 547 €/kW (4 h), O&M 15 €/kW·año, WACC 10,9 %, "
              "15 años; NREL/TP-6A40-93281 (reparto potencia/energía); Modo Energy (previsión 2028); DNV y Politecnico di "
              "Torino (degradación); Ley 15/2012 (IVPEE), RD 1544/2011 (peaje), Ley 27/2014 (IS). Simulación propia con ESIOS (REE) y OMIE.")


def _pct(x):
    return "—" if pd.isna(x) else n(100 * x, 1) + " %"


def rentabilidad(dk, png):
    f = RES / "finanzas.csv"
    if not f.exists():
        return None
    v = pd.read_csv(f)
    b = v[v.trayectoria == "base"].sort_values(["horas", "ingreso_base"]).set_index("escenario")
    otros = v.pivot(index="escenario", columns="trayectoria", values="tir_antes")
    tab = pd.DataFrame({
        "Escenario": [ALIAS.get(k, f"Barrido {n(b.loc[k, 'horas'])} h") for k in b.index],
        "CAPEX\n(k€/MW)": [n(x / 1000) for x in b["capex"]],
        "Ingreso base\n(k€/MW·año)": [n(x / 1000) for x in b["ingreso_base"]],
        "TIR antes IS\nbase": [_pct(x) for x in b["tir_antes"]],
        "TIR después IS\nbase": [_pct(x) for x in b["tir_despues"]],
        "VAN al 10,9 %\n(k€/MW)": [n(x / 1000) for x in b["van"]],
        "LCOS sin carga\n(€/MWh)": [n(x, 1) for x in b["lcos"]],
        "Recuperación\n(años)": ["—" if pd.isna(x) else n(x) for x in b["payback"]],
        "TIR antes IS\npersistencia": [_pct(otros.loc[k, "persistencia"]) for k in b.index],
        "TIR antes IS\nsaturación": [_pct(otros.loc[k, "saturacion"]) for k in b.index]})
    per = b["periodo_base"].iloc[0]
    fig = dk.hoja("Rentabilidad de los escenarios stand-alone (por MW de BESS)",
                  f"Año base {per}. Base: converge en 3 años a la previsión de Modo para 2028 (152 k€/MW·año en el 4 h operable; "
                  "mismo factor para todos) y queda plana en real. Persistencia: se repite el año base. Saturación: base y −5 %/año "
                  "desde 2028. Incluye degradación, O&M, IVPEE, peaje e IS; sin mecanismo de capacidad ni compra del proyecto.",
                  fuente=FUENTE_FIN)
    _tabla(fig, tab, (0.04, 0.10, 0.92, 0.64), ancho_col=[0.15] + [0.095] * 9, fs=9)
    dk.guardar(fig, png)
    return b


def barrido(dk, b, png):
    sel = b[[k.startswith("barrido") or k == "c_operable" for k in b.index]].sort_values("horas")
    if len(sel) < 3:
        return
    fig = dk.hoja("Barrido de duración (operable, 50 MW)",
                  "Barras: CAPEX e ingreso del año base por MW. Línea: TIR antes de impuestos (trayectoria base, eje derecho). "
                  "CAPEX = 152 €/kW + 98,75 €/kWh × horas (ACER 2030 para el 4 h; reparto de NREL). Mismo mercado, misma previsión "
                  "y mismas reglas en todas las duraciones; máximo 2 ciclos/día.", fuente=FUENTE_FIN)
    ax = dk.eje(fig)
    x = np.arange(len(sel))
    ax.bar(x - 0.2, sel["capex"] / 1000, 0.4, color=C["panel"], edgecolor=C["linea"], label="CAPEX (k€/MW)")
    ax.bar(x + 0.2, sel["ingreso_base"] / 1000, 0.4, color=C["verde"], label="Ingreso año base (k€/MW·año)")
    ax.set_xticks(x, [n(h) + " h" for h in sel["horas"]])
    ax.set_ylabel("k€/MW")
    ax2 = ax.twinx()
    ax2.plot(x, 100 * sel["tir_antes"], "o-", color=C["coral"], lw=2, label="TIR antes de IS (%)")
    for xi, v in zip(x, sel["tir_antes"]):
        ax2.text(xi, 100 * v + 0.8, _pct(v), ha="center", fontsize=9, color=C["coral"])
    ax2.set_ylabel("TIR (%)")
    ax2.set_ylim(0, max(100 * sel["tir_antes"].max() * 1.3, 10))
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, ncol=3, fontsize=9, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0))
    dk.guardar(fig, png)


def sensibilidad(dk, png):
    f = RES / "finanzas_sensibilidad.csv"
    if not f.exists():
        return
    s = pd.read_csv(f)
    tab = pd.DataFrame({"Caso (C operable 4 h, trayectoria base)": s["caso"], "TIR antes de IS": s["tir_antes"].map(_pct),
                        "TIR después de IS": s["tir_despues"].map(_pct), "VAN (k€/MW)": (s["van"] / 1000).map(n),
                        "LCOS sin carga\n(€/MWh)": s["lcos"].map(lambda x: n(x, 1))})
    rtb = s.loc[s["caso"].str.startswith("Compra"), "tir_antes"]
    resta = n(100 * (s["tir_antes"].iloc[0] - rtb.iloc[0]), 1) if len(rtb) else "—"
    fig = dk.hoja("Sensibilidad de la rentabilidad",
                  "Un parámetro cada vez sobre el caso base. El CAPEX es la palanca principal; comprar un proyecto listo para "
                  f"construir (~100 k€/MW) resta {resta} puntos de TIR. El mecanismo de capacidad (aprobado por la CE el "
                  "29-5-2026, operativo hacia 2030-2031) no está incluido.", fuente=FUENTE_FIN)
    _tabla(fig, tab, (0.10, 0.18, 0.80, 0.56), ancho_col=[0.36, 0.16, 0.16, 0.16, 0.16], fs=10.5)
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
        "generación FV peninsular real (ESIOS 1295) con la energía mensual de PVGIS 5.3 (JRC, SARAH3) en el emplazamiento "
        "(A y B: Badajoz, seguidor de un eje, pérdidas 14 %).",
        "Banda aFRR: precio en €/MW por hora; precio-aceptante en la réplica de UNEF; con tope de profundidad (fórmula pública de "
        "Modo Energy) en los escenarios «realistas». Cuartohoraria cuando el precio publicado cambia dentro de la hora.",
        "Previsión imperfecta (C operable y realista): diario y banda con la media cuarto a cuarto de los 7 días anteriores "
        "(captura del arbitraje en el diario: 92,9 % en 2025 y 95,7 % en 2026, fuera de muestra); sin subastas intradiarias; "
        "continuo en ventanas de 2 h con el precio de referencia (ESIOS 1727), con tope = energía casada en el cuarto (1442) "
        "y 2 P; ofertas de energía aFRR y mFRR al precio del diario del cuarto (sin activaciones con pérdida).",
        "Tiempo real (C operable y realista): las activaciones se limitan al SoC disponible cuarto a cuarto y se reponen en el "
        "continuo con 1 h y 1 cuarto de retraso (cierre 60 min antes de la entrega), al precio de cada cuarto.",
        "Rentabilidad: CAPEX, O&M, WACC y vida de ACER (España, 2030); degradación LFP 1 %/año + 3 % por 1.000 ciclos; IVPEE 7 % "
        "sobre las ventas de la descarga, peaje de generación 0,5 €/MWh e IS 25 %. Ingresos de mercado sin GdO, restricciones "
        "técnicas ni mecanismo de capacidad. Las cifras son referencias de optimización, no ingresos garantizados.",
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
    from . import finanzas
    try:
        finanzas.calcular()
    except Exception as ex:  # el informe de mercado no debe caer por la parte financiera
        print(f"Aviso: finanzas no calculadas ({ex})")
    fin = rentabilidad(dk, SAL / "rentabilidad.png")
    if fin is not None:
        barrido(dk, fin, SAL / "barrido.png")
        sensibilidad(dk, SAL / "sensibilidad.png")
    esc_dia = "unef_c" if "unef_c" in res else next(iter(res))
    dia_tipo(dk, esc_dia, SAL / "dia.png")
    metodologia(dk)
    dk.pdf.close()
    # web
    filas_html = "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td></tr>" for r in filas)
    figs = "".join(f'<h2>{nm}</h2><img src="{im}" alt="{nm}">' for nm, im in imgs)
    fin_html = ""
    if fin is not None:
        fin_html = '<h2>Rentabilidad (TIR, VAN, LCOS)</h2><img src="rentabilidad.png" alt="Rentabilidad">'
        if (SAL / "barrido.png").exists():
            fin_html += '<h2>Barrido de duración</h2><img src="barrido.png" alt="Barrido de duración">'
        fin_html += '<h2>Sensibilidad</h2><img src="sensibilidad.png" alt="Sensibilidad">'
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
{figs}<h2>Validación contra referencias públicas</h2><img src="validacion.png" alt="Validación">
{fin_html}<h2>Un día de operación</h2><img src="dia.png" alt="Día tipo">
<p style="font-size:.8rem;color:{C['gris']}">A, B, C, C techo y solo diario: previsión perfecta (cota superior). C operable y realista: deciden sin conocer los precios del día. Ingresos de mercado sin GdO, restricciones técnicas ni mecanismo de capacidad; la rentabilidad sí incluye CAPEX, O&amp;M, degradación, IVPEE, peaje de generación e IS.
Fuente: ESIOS (REE) y OMIE. Elaboración propia.</p></body></html>"""
    (SAL / "index.html").write_text(html, encoding="utf-8")
    print(f"Informe del simulador: {dk.n} páginas en {SAL}")


if __name__ == "__main__":
    generar()
