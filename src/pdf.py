"""Presentación en PDF (16:9) con matplotlib. Gratis, sin navegador ni servicios externos."""
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter
from matplotlib.colors import LinearSegmentedColormap, Normalize, TwoSlopeNorm
from matplotlib.patches import Circle, Ellipse, Rectangle

from .informe import _eje_semana, es_web
from .narrativa import etiqueta_dia, n, rango, redactar

W, H = 13.333, 7.5
TZ_ = 'Europe/Madrid'
C = dict(fondo="#F6F2EA", tinta="#1F2933", verde="#1E3D32", musgo="#5F8D4E", coral="#E4572E",
         ciruela="#6B4A7A", mostaza="#C9972B", gris="#6B7280", panel="#E9E2D3", linea="#D8D0BE",
         azul="#2B6F8F", marron="#8C5A3C")
PALETA = [C["coral"], C["verde"], C["ciruela"], C["musgo"], C["mostaza"], C["azul"], C["marron"], C["gris"]]
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": C["linea"], "axes.labelcolor": C["gris"],
                     "xtick.color": C["gris"], "ytick.color": C["gris"], "text.color": C["tinta"]})


def _fmt_eje(v, _=None):
    if abs(v - round(v)) < 1e-9:
        return n(v, 0)
    return n(v, 2).rstrip("0").rstrip(",")


class Deck:
    def __init__(self, ruta, marca, autor, periodo):
        self.pdf = PdfPages(ruta)
        self.marca, self.autor, self.periodo = marca, autor, periodo
        self.n = 0
        self.paginas = []
        self.img_dir = None

    # ---- marcos
    def _fig(self):
        fig = plt.figure(figsize=(W, H), facecolor=C["fondo"])
        self.n += 1
        fig._n = self.n
        return fig

    def diapositiva(self, titulo, lectura=None, fuente="Fuente: ESIOS (REE) y OMIE. Elaboración propia."):
        fig = self._fig()
        fig.add_artist(Rectangle((0, 0.982), 1, 0.018, color=C["verde"], transform=fig.transFigure))
        fig.add_artist(Rectangle((0.045, 0.905), 0.006, 0.05, color=C["coral"], transform=fig.transFigure))
        fig.text(0.06, 0.93, titulo, fontsize=22, fontweight="bold", color=C["verde"], va="center")
        if lectura:
            fig.add_artist(Rectangle((0.045, 0.80), 0.91, 0.085, color=C["panel"], transform=fig.transFigure))
            fig.text(0.06, 0.8425, textwrap.fill(lectura, 150), fontsize=10.5, va="center", linespacing=1.35)
        fig.text(0.045, 0.014, textwrap.fill(fuente, 150), fontsize=7, color=C["gris"], va="bottom", linespacing=1.25)
        pie = f"{self.marca} · {self.periodo}  ·  {self.n}"
        fig.text(0.955, 0.03, pie, fontsize=7.5, color=C["gris"], ha="right")
        fig._titulo = titulo
        return fig

    def eje(self, fig, lectura=True, caja=None):
        top = 0.74 if lectura else 0.86
        ax = fig.add_axes(caja or [0.07, 0.17, 0.875, top - 0.17])
        ax.set_facecolor("none")
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.grid(axis="y", color=C["linea"], linewidth=0.7)
        ax.set_axisbelow(True)
        ax.yaxis.set_major_formatter(FuncFormatter(_fmt_eje))
        return ax

    def guardar(self, fig):
        self.pdf.savefig(fig, facecolor=fig.get_facecolor())
        if self.img_dir is not None and es_web(getattr(fig, "_titulo", None)):
            num = getattr(fig, "_n", self.n)
            nombre = f"{num:02d}.webp"
            try:
                fig.savefig(self.img_dir / nombre, format="webp", dpi=100, facecolor=fig.get_facecolor(), pil_kwargs={"quality": 82})
            except Exception:
                nombre = f"{num:02d}.png"
                fig.savefig(self.img_dir / nombre, format="png", dpi=100, facecolor=fig.get_facecolor())
            self.paginas.append({"n": num, "img": nombre, "titulo": getattr(fig, "_titulo", None), "sep": getattr(fig, "_sep", None)})
        plt.close(fig)

    def cerrar(self):
        self.pdf.close()


def _ejes_dias(ax, idx):
    tv, tt = _eje_semana(idx)
    ax.set_xticks(tv)
    ax.set_xticklabels(tt)
    ax.set_xlim(0, len(idx))
    for x in tv[1:]:
        ax.axvline(x, color=C["linea"], linewidth=0.6)


def _leyenda(ax, ncol=4):
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=ncol, frameon=False, fontsize=9)


# ------------------------------------------------------------------ diapositivas
def portada(d, res, cfg):
    fig = d._fig()
    fig.add_artist(Rectangle((0, 0), 0.5, 1, color=C["verde"], transform=fig.transFigure))
    fig.add_artist(Rectangle((0, 0), 0.5, 0.012, color=C["coral"], transform=fig.transFigure))
    asp = H / W
    for r, a in ((0.40, 0.0), (0.30, 0.12), (0.20, 0.25), (0.10, 0.4)):
        fig.add_artist(Ellipse((0.75, 0.52), 2 * r * asp, 2 * r, transform=fig.transFigure, fill=False,
                               edgecolor=C["coral"], linewidth=2.2, alpha=0.30 + a, zorder=1))
    fig.add_artist(Ellipse((0.75, 0.52), 0.12 * asp, 0.12, transform=fig.transFigure, color=C["coral"]))
    fig.text(0.06, 0.62, textwrap.fill(cfg.get("marca", "Radar del mercado eléctrico"), 15), fontsize=34,
             fontweight="bold", color="white", va="center", linespacing=1.1)
    fig.text(0.06, 0.40, f"Semana {res['etiqueta'][-2:]} de {res['etiqueta'][:4]}\n{rango(res)}", fontsize=17,
             color="#C9DCCB", va="top", linespacing=1.5)
    fig.text(0.06, 0.14, "Mercados diario e intradiarios, servicios de balance,\nbaterías y demanda del sistema peninsular",
             fontsize=11, color="#A8C2AB", va="top", linespacing=1.5)
    if res.get("provisional"):
        fig.text(0.06, 0.25, "EDICIÓN PROVISIONAL · sin liquidación I3", fontsize=11, fontweight="bold", color="#FFD27A")
        fig.text(0.06, 0.215, "Las secciones del I3 se añaden solas cuando REE lo publica (hacia el viernes).", fontsize=9, color="#C9DCCB")
    pie = "Elaboración propia con datos públicos de ESIOS (REE) y OMIE"
    if cfg.get("autor"):
        pie += f" · {cfg['autor']}"
    fig.text(0.53, 0.05, pie, fontsize=9, color=C["gris"])
    d.guardar(fig)


def separador(d, num, titulo, sub):
    fig = d._fig()
    fig.add_artist(Rectangle((0, 0), 0.42, 1, color=C["verde"], transform=fig.transFigure))
    fig.text(0.06, 0.55, f"{num:02d}", fontsize=80, fontweight="bold", color=C["coral"], va="center")
    fig.text(0.47, 0.58, textwrap.fill(titulo, 24), fontsize=28, fontweight="bold", color=C["verde"], va="center", linespacing=1.15)
    fig.text(0.47, 0.42, textwrap.fill(sub, 55), fontsize=13, color=C["gris"], va="top")
    fig._sep = (num, titulo, sub)
    d.guardar(fig)


def resumen(d, res, t):
    fig = d.diapositiva("Resumen de la semana", fuente="Fuente: ESIOS (REE) y OMIE. Techo de arbitraje: cálculo propio, solo mercado diario.")
    kp = [
        ("Precio medio", f"{n(res['precio_medio'])}", "€/MWh", f"{n(res['var_prev'], 1, True)} % vs semana anterior"),
        ("Horas a precio ≤ 0", f"{n(res['horas_neg'], 1)}", "h", f"mínimo {n(res['precio_min'], 1)} €/MWh"),
        ("Spread diario medio", f"{n(res['spread_medio'], 0)}", "€/MWh", "máx − mín de cada día"),
        ("Techo arbitraje BESS", f"{n(res['bess_dia'], 0)}", "€/MW·día", f"batería {int(res['_bat_horas'])} h, solo diario"),
    ]
    if "gen_solar_fv" in res["captura"]:
        c = res["captura"]["gen_solar_fv"]
        kp.append(("Solar capturó", f"{n(c['ratio'], 0)}", "% del medio", f"{n(c['precio'])} €/MWh"))
    if res.get("mix"):
        kp.append(("Renovables", f"{n(res['mix']['renovable_pct'], 0)}", "% de la generación", f"máx. {n(res['mix']['renovable_max'], 0)} % en un cuarto"))
    ancho = 0.91 / len(kp)
    for i, (a, b, u, s) in enumerate(kp):
        x = 0.045 + i * ancho
        fig.add_artist(Rectangle((x + 0.005, 0.60), ancho - 0.012, 0.2, color=C["panel"], transform=fig.transFigure))
        fig.add_artist(Rectangle((x + 0.005, 0.60), 0.004, 0.2, color=PALETA[i % len(PALETA)], transform=fig.transFigure))
        fig.text(x + 0.02, 0.775, a, fontsize=9, color=C["gris"])
        fig.text(x + 0.02, 0.70, b, fontsize=30 if len(kp) <= 5 else 25, fontweight="bold", color=C["verde"])
        fig.text(x + 0.02, 0.655, u, fontsize=9.5, color=C["gris"])
        fig.text(x + 0.02, 0.615, s, fontsize=8.5, color=C["gris"])
    pts = [t["titular"], t["h_calor"] + ". " + t["p_calor"].split(". ")[0] + ".", t.get("p_bess", "")]
    if t.get("p_bat"):
        pts.append(t["p_bat"])
    if t.get("h_solar"):
        pts.append(t["h_solar"] + ".")
    if t.get("h_dem"):
        pts.append(t["h_dem"] + ".")
    if res.get("provisional"):
        fig.text(0.06, 0.555, "Edición provisional: las secciones basadas en la liquidación I3 de REE se añadirán automáticamente cuando se publique (hacia el viernes).",
                 fontsize=9.5, color=C["coral"], fontweight="bold")
    y = 0.52
    pts = [p for p in pts if p]
    fs, ancho, paso = (11.5, 120, 0.036) if len(pts) <= 5 else (10.5, 135, 0.032)
    for p in pts:
        txt = textwrap.fill(p, ancho)
        fig.add_artist(Circle((0.055, y - 0.004), 0.0045, color=C["coral"], transform=fig.transFigure))
        fig.text(0.07, y + 0.012, txt, fontsize=fs, va="top", linespacing=1.35)
        y -= paso * (txt.count("\n") + 1) + 0.024
    d.guardar(fig)


def precios(d, res, cfg):
    series = [("Mercado diario", res["spot"])]
    for k, v in cfg.get("opcionales", {}).items():
        if v.get("tipo") == "precio" and k in res["series"] and res["series"][k].notna().mean() > 0.3:
            series.append((v["nombre"], res["series"][k]))
    if len(series) < 2:
        return
    fig = d.diapositiva("Precio de los mercados de energía",
                        "Precio de cada sesión en cada cuarto de hora. Donde el mercado es horario, el valor se repite en los cuatro cuartos. "
                        "Con varias series superpuestas, el diario marca la referencia y el resto muestra cuánto se desvía.")
    ax = d.eje(fig)
    for i, (nom, s) in enumerate(series):
        ax.plot(range(len(s)), s.values, lw=2.2 if i == 0 else 1.1, color=C["tinta"] if i == 0 else PALETA[(i - 1) % len(PALETA)],
                label=nom, alpha=1 if i == 0 else 0.85)
    ax.axhline(0, color=C["gris"], lw=0.8)
    _ejes_dias(ax, series[0][1].index)
    ax.set_ylabel("€/MWh")
    _leyenda(ax, 5)
    d.guardar(fig)


def mapa_calor(d, res):
    t = redactar(res)
    fig = d.diapositiva("Mapa de precios del mercado diario: dónde está el valor", t["p_calor"],
                        "Fuente: OMIE vía ESIOS. Puntos oscuros: carga óptima; puntos blancos: descarga óptima de una batería de 1 MW / 4 h.")
    ax = d.eje(fig, caja=[0.12, 0.13, 0.78, 0.60])
    ax.grid(False)
    z = res["calor"]
    zmin, zmax = float(np.nanmin(z)), float(np.nanpercentile(z, 99))
    if zmin < 0:
        cm = LinearSegmentedColormap.from_list("p", [C["coral"], C["fondo"], "#A9CBA0", C["musgo"], C["verde"]])
        norm = TwoSlopeNorm(vmin=zmin, vcenter=0, vmax=max(zmax, 1))
    else:
        cm = LinearSegmentedColormap.from_list("p", [C["fondo"], "#A9CBA0", C["musgo"], C["verde"]])
        norm = Normalize(vmin=0, vmax=max(zmax, 1))
    im = ax.imshow(z, aspect="auto", cmap=cm, norm=norm, interpolation="nearest")
    c, de = res["marcas_carga"], res["marcas_desc"]
    ax.scatter(c[0], c[1], s=7, color=C["tinta"], zorder=3)
    ax.scatter(de[0], de[1], s=7, color="white", edgecolor=C["tinta"], linewidth=0.4, zorder=3)
    ax.set_yticks(range(len(res["dias"])))
    ax.set_yticklabels([etiqueta_dia(x) for x in res["dias"]])
    ax.set_xticks(range(0, 96, 8))
    ax.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)])
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cb.set_label("€/MWh", color=C["gris"])
    cb.outline.set_visible(False)
    d.guardar(fig)


def perfil(d, res):
    fig = d.diapositiva("La forma del día: esta semana frente a las cuatro anteriores",
                        "Precio medio por hora del reloj. La diferencia entre ambas curvas indica si el valle del mediodía se profundiza "
                        "o si la punta de la tarde se estrecha, que es lo que decide el valor de una batería.")
    ax = d.eje(fig)
    pa, pp = res["perfil_act"], res["perfil_prev"]
    ax.fill_between(pa.index / 60, pa.values, pp.reindex(pa.index).values, color=C["coral"], alpha=0.12)
    ax.plot(pp.index / 60, pp.values, color=C["gris"], lw=2, ls="--", label="Media 4 semanas anteriores")
    ax.plot(pa.index / 60, pa.values, color=C["verde"], lw=3.2, label="Esta semana")
    ax.axhline(0, color=C["gris"], lw=0.8)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)])
    ax.set_xlim(0, 23.75)
    ax.set_ylabel("€/MWh")
    _leyenda(ax, 2)
    d.guardar(fig)


def bateria(d, res, cfg, t):
    bat = cfg["bateria"]
    fig = d.diapositiva(t["h_bess"], t["p_bess"],
                        "Fuente: OMIE vía ESIOS. Cálculo propio por programación dinámica exacta con previsión perfecta: es un techo, no un ingreso garantizado.")
    ax = d.eje(fig, caja=[0.07, 0.12, 0.56, 0.62])
    vals = [res["bess_por_dia"].get(x, np.nan) for x in res["dias"]]
    barras = ax.bar([etiqueta_dia(x) for x in res["dias"]], vals, color=C["verde"], width=0.62)
    mx = np.nanmax(vals) if not np.all(np.isnan(vals)) else 1
    for b, v in zip(barras, vals):
        if not np.isnan(v):
            ax.text(b.get_x() + b.get_width() / 2, v + mx * 0.02, n(v, 0), ha="center", fontsize=10, fontweight="bold")
    ax.set_ylabel("€/MW·día")
    fig.add_artist(Rectangle((0.67, 0.12), 0.285, 0.62, color=C["panel"], transform=fig.transFigure))
    fig.text(0.685, 0.715, "Supuestos del cálculo", fontsize=12, fontweight="bold", color=C["verde"])
    sup = (f"Batería de 1 MW y {int(bat['horas'])} MWh\nRendimiento ida y vuelta: {int(bat['rendimiento_ida_vuelta'] * 100)} %\n"
           f"Coste de ciclado: {n(bat['coste_ciclado_eur_mwh'], 0)} €/MWh\nTope: {n(bat.get('ciclos_max_dia', 1.5), 1)} ciclos al día\n"
           "Solo mercado diario (15 min)\nEmpieza y acaba cada día vacía\n\n"
           + textwrap.fill("No incluye aFRR, mFRR ni intradiarios, que añaden ingreso real pero dependen de la participación y de la potencia contratada.", 40))
    fig.text(0.685, 0.68, sup, fontsize=9.5, va="top", linespacing=1.55)
    fig.text(0.685, 0.20, f"Semana: {n(res['bess_semana'], 0)} €/MW\nMedia anterior: {n(res['bess_prev'], 0)} €/MW·día",
             fontsize=10.5, fontweight="bold", color=C["coral"], linespacing=1.5)
    d.guardar(fig)


def lineas_tipo(d, res, cfg, tipo, titulo, lectura, unidad, fuente=None, minimo=1):
    ks = [k for k, v in cfg.get("opcionales", {}).items()
          if v.get("tipo") == tipo and k in res["series"] and res["series"][k].notna().mean() > 0.3]
    if len(ks) < minimo or not ks:
        return
    fig = d.diapositiva(titulo, lectura, fuente or "Fuente: ESIOS (REE), indicadores agregados por cuarto de hora.")
    ax = d.eje(fig)
    for i, k in enumerate(ks):
        s = res["series"][k]
        ax.plot(range(len(s)), s.values, lw=1.8, color=PALETA[i % len(PALETA)], label=cfg["opcionales"][k]["nombre"])
    _ejes_dias(ax, res["series"][ks[0]].index)
    ax.set_ylabel(unidad)
    _leyenda(ax, 4)
    d.guardar(fig)


def demanda(d, res, t):
    dem = res["demanda"]
    if not dem:
        return
    fig = d.diapositiva(t["h_dem"], "Demanda real frente a la prevista y la programada. " + t["p_dem"],
                        "Fuente: ESIOS (REE), demanda real, prevista y programada.")
    ax = d.eje(fig)
    ax.plot(range(len(dem["real"])), dem["real"].values, color=C["verde"], lw=2.2, label="Real")
    if "prevista" in dem:
        ax.plot(range(len(dem["prevista"])), dem["prevista"].values, color=C["coral"], lw=1.3, ls="--", label="Prevista")
    prog = res["series"].get("demanda_programada")
    if prog is not None and prog.notna().mean() > 0.3:
        ax.plot(range(len(prog)), prog.values, color=C["ciruela"], lw=1.3, ls=":", label="Programada")
    _ejes_dias(ax, dem["real"].index)
    ax.set_ylabel("MW")
    ax.set_ylim(bottom=0)
    _leyenda(ax, 3)
    d.guardar(fig)


def captura(d, res, cfg, t):
    cs = res["captura"]
    if not cs:
        return
    fig = d.diapositiva(t.get("h_solar", "Precio capturado por tecnología"), t.get("p_solar", ""),
                        "Fuente: ESIOS (REE). Precio capturado = Σ(precio × generación) / Σ generación, con generación en tiempo real y precio diario. Aproximación, no liquidación.")
    ax = d.eje(fig, caja=[0.07, 0.12, 0.45, 0.62])
    nombres = {"gen_solar_fv": "Solar FV", "gen_eolica": "Eólica"}
    ks = list(cs)
    x = np.arange(len(ks) + 1)
    vals = [res["precio_medio"]] + [cs[k]["precio"] for k in ks]
    cols = [C["gris"]] + [C["coral"] if k == "gen_solar_fv" else C["azul"] for k in ks]
    b = ax.bar(x, vals, color=cols, width=0.55)
    ax.set_xticks(x)
    ax.set_xticklabels(["Precio medio"] + [nombres[k] for k in ks])
    for r, v in zip(b, vals):
        ax.text(r.get_x() + r.get_width() / 2, v + max(vals) * 0.02, n(v), ha="center", fontweight="bold")
    ax.set_ylabel("€/MWh")
    ax2 = fig.add_axes([0.56, 0.12, 0.385, 0.62])
    ax2.set_facecolor("none")
    for sp in ("top", "right"):
        ax2.spines[sp].set_visible(False)
    ax2.grid(axis="y", color=C["linea"], lw=0.7)
    for k in ks:
        g = res["series"][k]
        ax2.plot(range(len(g)), g.values / 1000, lw=1.2, color=C["coral"] if k == "gen_solar_fv" else C["azul"], label=nombres[k])
    _ejes_dias(ax2, res["series"][ks[0]].index)
    ax2.set_ylabel("GW")
    ax2.set_title("Generación en tiempo real", fontsize=10, color=C["gris"], loc="left")
    ax2.legend(frameon=False, fontsize=9, loc="upper right")
    d.guardar(fig)


def tabla_mercados(d, res, cfg):
    filas = []

    def stats(nom, mag, uni, s, total=False):
        if s is None or s.notna().mean() < 0.3:
            return
        v = s.dropna()
        cub = f"{v.index[0].tz_convert(TZ_).strftime('%d-%m')} a {v.index[-1].tz_convert(TZ_).strftime('%d-%m')}"
        tot = n(s.sum() / 4, 0) if total else "—"
        filas.append((nom, mag, uni, cub, n(s.mean()), n(s.min()), n(s.max()), tot))
    stats("Mercado diario", "Precio", "€/MWh", res["spot"])
    for k, v in cfg.get("opcionales", {}).items():
        s = res["series"].get(k)
        mag = {"precio": "Precio", "banda_precio": "Precio banda", "banda_mw": "Banda (MW)",
               "energia": "Energía", "potencia": "Generación"}.get(v.get("tipo"), "")
        stats(v["nombre"], mag, v.get("unidad", ""), s, total=v.get("tipo") in ("energia", "potencia"))
    for k, nom in (("demanda_real", "Demanda real"), ("demanda_prevista", "Demanda prevista"), ("demanda_programada", "Demanda programada")):
        stats(nom, "Potencia", "MW", res["series"].get(k), total=(k == "demanda_real"))
    por = 14
    for pag in range(0, len(filas), por):
        fig = d.diapositiva("Qué publicó cada mercado" + (f" ({pag // por + 1}/{(len(filas) - 1) // por + 1})" if len(filas) > por else ""),
                            "Medio, mínimo y máximo se calculan sobre los valores de cada cuarto de hora, y el total solo tiene sentido en la energía (potencia media dividida entre cuatro). "
                            "La energía de mercados distintos no se puede sumar.")
        cols = ["Mercado", "Magnitud", "Unidad", "Cubre", "Medio", "Mínimo", "Máximo", "Total (MWh)"]
        xs = [0.055, 0.30, 0.43, 0.51, 0.66, 0.75, 0.84, 0.935]
        al = ["left", "left", "left", "left", "right", "right", "right", "right"]
        fig.add_artist(Rectangle((0.045, 0.725), 0.91, 0.045, color=C["verde"], transform=fig.transFigure))
        for x, c, a_ in zip(xs, cols, al):
            fig.text(x, 0.7475, c, color="white", fontsize=9.5, fontweight="bold", va="center", ha=a_)
        for i, fila in enumerate(filas[pag:pag + por]):
            y = 0.70 - i * 0.0415
            if i % 2 == 0:
                fig.add_artist(Rectangle((0.045, y - 0.0207), 0.91, 0.0415, color=C["panel"], transform=fig.transFigure))
            for x, v, a_ in zip(xs, fila, al):
                fig.text(x, y, v, fontsize=8.6, va="center", ha=a_)
        d.guardar(fig)


def tendencia(d, res, t):
    fig = d.diapositiva(t["h_tend"],
                        "Cinco semanas seguidas, la actual incluida. El precio medio y el techo de arbitraje no siempre se mueven juntos: "
                        "lo que paga a una batería es la forma del día y el spread, no el nivel del precio.")
    ax = d.eje(fig)
    s = res["semanas"]
    x = np.arange(len(s))
    ax.bar(x, [v["bess_dia"] for v in s], color=C["mostaza"], width=0.55, label="Techo arbitraje (€/MW·día)")
    for xi, v in zip(x, s):
        ax.text(xi, v["bess_dia"] + 4, n(v["bess_dia"], 0), ha="center", fontsize=9, color=C["marron"])
    ax.set_ylabel("€/MW·día")
    ax.set_xticks(x)
    ax.set_xticklabels([v["corta"] for v in s])
    ax.set_ylim(0, np.nanmax([v["bess_dia"] for v in s] + [1.0]) * 1.25)
    ax2 = ax.twinx()
    ax2.set_ylim(0, np.nanmax([v["precio_medio"] for v in s] + [1.0]) * 1.25)
    ax2.plot(x, [v["precio_medio"] for v in s], color=C["verde"], lw=3, marker="o", label="Precio medio (€/MWh)")
    ax2.set_ylabel("€/MWh")
    ax2.spines["top"].set_visible(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=2, frameon=False)
    d.guardar(fig)


def metodologia(d, res, cfg, meta, i3_estado=None):
    fig = d.diapositiva("Cómo leer este informe", fuente="El panel de mercados es de ESIOS y refleja lo publicado en el momento de generar el informe; el I3 llega a los cuatro días y el I90, a los noventa.")
    notas = [
        "El signo es el que publica REE: la compra es negativa, así que un ingreso negativo es un coste.",
        "Las celdas vacías son conceptos que REE no valora (bilaterales, indisponibilidades, desvíos comerciales), no ceros.",
        "La energía de mercados distintos no se puede sumar: lo vendido en el diario y recomprado en restricciones aparecería dos veces. El ingreso sí se suma, porque son euros.",
        "Las restricciones salen del I3, que agrega por tecnología: aquí no hay unidad de programación ni empresa. El detalle activo a activo está en el I90, con noventa días de retraso.",
        "En restricciones, el precio publicado no se abre por tipo: el €/MWh de COT y el de SOT de una misma fila son el mismo.",
        "El coste base de la operación reforzada es un contrafactual, no una liquidación: supone que sin el apagón el control de tensión habría seguido costando lo de los cuatro primeros meses de 2025.",
        "El €/MVArh depende del ángulo entre activa y reactiva, que no es observable. Aquí se ha usado α = 45°.",
        "Techo de arbitraje, ratio de captura y semáforos son cálculos propios de este informe con datos públicos: sirven para comparar semanas, no son ingresos ni recomendaciones.",
        "Calendario: el lunes se publica la edición provisional (mercados, balance, mix y baterías) y, en cuanto REE publica el I3 de los siete días (D+4, hacia el viernes), el informe se regenera solo con todas las secciones.",
    ]
    y = 0.84
    for p in notas:
        txt = textwrap.fill(p, 150)
        fig.add_artist(Circle((0.055, y - 0.004), 0.0035, color=C["coral"], transform=fig.transFigure))
        fig.text(0.068, y + 0.009, txt, fontsize=10, va="top", linespacing=1.4)
        y -= 0.036 * (txt.count("\n") + 1) + 0.022
    if i3_estado:
        fig.text(0.06, 0.09, textwrap.fill("Estado del I3: " + " ".join(i3_estado), 170), fontsize=8.5, color=C["gris"], va="top")
    d.guardar(fig)
    fig = d.diapositiva("Series utilizadas y su cobertura", fuente="Cobertura = porcentaje de cuartos de hora de la semana con dato. El IDA3 cubre por diseño solo de 12:00 a 24:00 (≈ 50 %); en el resto, una cobertura baja es un día que el mercado no se celebró o que ESIOS aún no ha publicado.")
    y = 0.80
    cob = list(res["cobertura"].items())
    mitad = (len(cob) + 1) // 2
    for col, tramo in enumerate((cob[:mitad], cob[mitad:])):
        yy = y
        x0 = 0.05 + col * 0.47
        for k, c in tramo:
            m = meta.get(k, {})
            fig.text(x0, yy, textwrap.shorten(str(m.get("nombre", k)), 30), fontsize=8.5, va="center")
            fig.text(x0 + 0.28, yy, f"ID {m.get('id', '—')}", fontsize=8.5, va="center", color=C["gris"])
            fig.text(x0 + 0.42, yy, f"{c * 100:.0f} %", fontsize=8.5, va="center", ha="right", color=C["verde"] if c > 0.97 else C["coral"])
            yy -= 0.034
    avisos = [f"{m['nombre']}: {m['aviso']}" for m in meta.values() if m.get("aviso")]
    if avisos:
        fig.text(0.05, 0.13, textwrap.fill("Avisos: " + " | ".join(avisos), 190), fontsize=8, color=C["coral"], va="top")
    d.guardar(fig)


# ------------------------------------------------------------------ orquestación
def generar_pdf(res, cfg, meta, ruta, demo=False, i3=None, i3_hist=None, i3_estado=None, img_dir=None):
    """i3: tabla I3 de la semana (o None). i3_hist: histórico desde 2025-01-01 (o None)."""
    from . import extras as X
    from . import pdf_i3 as P3

    t = redactar(res)
    per = f"semana {res['etiqueta'][-2:]}/{res['etiqueta'][:4]}"
    d = Deck(ruta, cfg.get("marca", "Radar del mercado eléctrico"), cfg.get("autor", ""), per)
    d.img_dir = img_dir
    dias = pd.DatetimeIndex([pd.Timestamp(x) for x in res["dias"]])
    rango_i3 = f"{res['dias'][0]} a {res['dias'][-1]} (7 días)"
    portada(d, res, cfg)
    resumen(d, res, t)
    X.sec_senales(d, res, cfg)
    # ---- 01 mercados
    separador(d, 1, "Los mercados del periodo", "Precio, energía casada, servicios de balance y demanda, cuarto de hora a cuarto de hora.")
    precios(d, res, cfg)
    lineas_tipo(d, res, cfg, "banda_precio", "Precio de la banda de aFRR",
                "La banda se contrata en potencia, no en energía: su precio va en €/MW y por eso no cabe en el mismo eje que el resto.", "€/MW")
    lineas_tipo(d, res, cfg, "energia", "Energía casada",
                "Energía casada en cada cuarto de hora, leída como potencia. En MWh por cuarto de hora todas las cifras saldrían divididas entre cuatro. "
                "La energía de cada mercado no se puede sumar entre sí: lo vendido en el diario y recomprado en un intradiario aparecería dos veces.", "MW")
    lineas_tipo(d, res, cfg, "banda_mw", "Banda de aFRR: asignada y requerida", "Potencia reservada en cada sentido (asignada, ID 632/633) y la que pide REE (requerida, ID 630/631).", "MW")
    demanda(d, res, t)
    X.sec_mix(d, res)
    tabla_mercados(d, res, cfg)
    ok3 = i3 is not None and len(i3) > 0
    if ok3:
        # ---- 02 sector
        separador(d, 2, "Sector: la foto por tecnología (I3)", "Qué cobra cada tecnología en cada mercado, con la liquidación publicada por REE.")
        P3.precio_capturado(d, i3, rango_i3)
        P3.ingreso_tabla(d, i3, rango_i3)
        P3.ingreso_dos_escalas(d, i3, rango_i3)
        for tec, nom in P3.TEC_CLAVE:
            P3.tecnologia_detalle(d, i3, tec, {"Solar FV": "Solar fotovoltaica"}.get(nom, nom.replace("Almac. gen.", "Almacenamiento generación").replace("Almac. cons.", "Almacenamiento consumo")), dias, rango_i3)
        # ---- 03 restricciones
        separador(d, 3, "Restricciones técnicas (I3)", "Cómo se mueve la energía entre el programa del mercado y el programa final, y quién paga el control de tensión.")
        P3.sankey(d, i3, None, "Toda la energía · cascada de programas",
                  "La cadena de programas del PO 3.1, con el ancho de cada cinta proporcional a la energía. Las restricciones entran dos veces: las del PBF antes de la primera sesión de intradiario "
                  "y las de tiempo real después. En el conjunto del sistema las dos ramas casi se cancelan: las restricciones no crean ni destruyen energía, la mueven de unas tecnologías a otras.", rango_i3)
        P3.tabla_recorte(d, i3, rango_i3)
        for tec, nom in (("Solar fotovoltaica", "Solar fotovoltaica"), ("Eólica", "Eólica"), ("Solar térmica", "Solar térmica")):
            P3.sankey(d, i3, tec, f"{nom} · cascada de programas",
                      "La misma cadena para una sola tecnología. Aquí la rama de subir prácticamente no existe: a una renovable las restricciones le quitan energía, casi nunca se la piden.", rango_i3)
            P3.programa_dia(d, i3, tec, nom, dias, rango_i3)
        P3.fase_tipologia(d, i3, dias, rango_i3)
        P3.tabla_fases(d, i3, rango_i3)
        P3.reparto_tecnologia(d, i3, rango_i3)
        P3.cot_sot_dia(d, i3, dias, rango_i3)
        if i3_hist is not None and len(i3_hist):
            f0, f1 = i3_hist["fecha"].min().date(), i3_hist["fecha"].max().date()
            P3.operacion_reforzada(d, i3_hist, f"{f0} a {f1} ({(f1 - f0).days + 1} días)")
    # ---- 04 lectura propia
    n_sec = 4 if ok3 else 2
    separador(d, n_sec, "Almacenamiento y renovables: lectura propia", "Lo que el mercado dice sobre baterías, solar y servicios de balance, más allá de las liquidaciones.")
    mapa_calor(d, res)
    X.sec_duracion_precios(d, res)
    X.sec_rango_diario(d, res)
    perfil(d, res)
    bateria(d, res, cfg, t)
    X.sec_baterias(d, res)
    X.sec_duraciones(d, res, cfg)
    X.sec_banda(d, res, cfg)
    X.sec_primas(d, res, cfg)
    captura(d, res, cfg, t)
    X.sec_canibalizacion(d, res)
    X.sec_residual(d, res)
    if not X.sec_historico(d, res):
        tendencia(d, res, t)
    X.sec_glosario(d)
    metodologia(d, res, cfg, meta, i3_estado)
    d.cerrar()
    return d.n, d.paginas
