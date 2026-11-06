"""Construye los gráficos (Plotly, como JSON) y renderiza la plantilla HTML."""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .narrativa import etiqueta_dia, n, rango, redactar

TZ = "Europe/Madrid"
RAIZ = Path(__file__).resolve().parent.parent


def _l(a):
    """Lista JSON-segura (NaN -> None)."""
    out = []
    for v in np.asarray(a, dtype=object).tolist() if not isinstance(a, list) else a:
        if isinstance(v, (float, np.floating)):
            out.append(None if (np.isnan(v) or np.isinf(v)) else round(float(v), 3))
        else:
            out.append(v)
    return out


def _eje_semana(idx):
    """Ticks al inicio de cada día local (correcto con días de 23/25 h)."""
    loc = idx.tz_convert(TZ)
    vals, txt, ult = [], [], None
    for i, t in enumerate(loc):
        if t.date() != ult:
            vals.append(i)
            txt.append(etiqueta_dia(t.date()))
            ult = t.date()
    return vals, txt


def graficos(res):
    ch = {}
    dias = res["dias"]
    ylab = [etiqueta_dia(d) for d in dias]

    # --- mapa de calor
    z = res["calor"]
    zmin = float(min(0, np.nanmin(z)))
    zmax = float(np.nanpercentile(z, 99))
    z0 = (0 - zmin) / (zmax - zmin) if zmax > zmin else 0
    esc = [[0, "#b23a48"], [z0, "#f1ede4"]] if z0 > 0.001 else [[0, "#f1ede4"]]
    for f, c in ((0.35, "#7fc6c1"), (0.7, "#1f7a8c"), (1, "#10263a")):
        esc.append([round(z0 + (1 - z0) * f, 4), c])
    txt = [[f"{s // 4:02d}:{(s % 4) * 15:02d}" for s in range(96)]] * len(dias)
    c, d = res["marcas_carga"], res["marcas_desc"]
    ch["g_calor"] = {
        "data": [
            {
                "type": "heatmap", "z": [_l(r) for r in z], "x": list(range(96)), "y": ylab,
                "text": txt, "colorscale": esc, "zmin": zmin, "zmax": zmax, "hoverongaps": False,
                "hovertemplate": "%{y} · %{text}<br>%{z:.1f} €/MWh<extra></extra>",
                "colorbar": {"thickness": 10, "len": 0.9, "title": {"text": "€/MWh"}},
            },
            {
                "type": "scatter", "mode": "markers", "name": "Carga óptima", "x": c[0], "y": [ylab[i] for i in c[1]],
                "marker": {"size": 4, "color": "#13212c"}, "hoverinfo": "skip",
            },
            {
                "type": "scatter", "mode": "markers", "name": "Descarga óptima", "x": d[0], "y": [ylab[i] for i in d[1]],
                "marker": {"size": 4, "color": "#ffffff", "line": {"width": 0.6, "color": "#13212c"}}, "hoverinfo": "skip",
            },
        ],
        "layout": {
            "height": 330, "margin": {"l": 52, "r": 10, "t": 8, "b": 56},
            "xaxis": {"tickvals": list(range(0, 96, 8)), "ticktext": [f"{h:02d}h" for h in range(0, 24, 2)], "showgrid": False},
            "yaxis": {"type": "category", "autorange": "reversed", "showgrid": False},
            "legend": {"orientation": "h", "y": -0.2, "x": 0},
        },
    }

    # --- ingreso diario batería
    vals = [res["bess_por_dia"].get(x, np.nan) for x in dias]
    ch["g_bess"] = {
        "data": [{
            "type": "bar", "x": ylab, "y": _l(vals), "marker": {"color": "#1f7a8c"},
            "text": [n(v, 0) if not np.isnan(v) else "" for v in vals], "textposition": "outside",
            "hovertemplate": "%{x}<br>%{y:.0f} €/MW<extra></extra>",
        }],
        "layout": {"height": 260, "margin": {"l": 52, "r": 10, "t": 20, "b": 36},
                   "yaxis": {"title": {"text": "€/MW·día"}, "rangemode": "tozero"}},
    }

    # --- perfil intradía
    pa, pp = res["perfil_act"], res["perfil_prev"]
    ch["g_perfil"] = {
        "data": [
            {"type": "scatter", "mode": "lines", "name": "Esta semana", "x": _l(list(pa.index / 60)), "y": _l(pa.values),
             "line": {"color": "#1f7a8c", "width": 3}},
            {"type": "scatter", "mode": "lines", "name": "Media 4 semanas anteriores", "x": _l(list(pp.index / 60)), "y": _l(pp.values),
             "line": {"color": "#8a99a4", "width": 2, "dash": "dash"}},
        ],
        "layout": {"height": 290, "margin": {"l": 52, "r": 10, "t": 8, "b": 40},
                   "xaxis": {"tickvals": list(range(0, 24, 3)), "ticktext": [f"{h:02d}h" for h in range(0, 24, 3)]},
                   "yaxis": {"title": {"text": "€/MWh"}}, "legend": {"orientation": "h", "y": -0.22}},
    }

    # --- tendencia 5 semanas (+ historial)
    s = res["semanas"]
    ch["g_tend"] = {
        "data": [
            {"type": "bar", "name": "Techo batería (€/MW·día)", "x": [x["corta"] for x in s], "y": _l([x["bess_dia"] for x in s]),
             "marker": {"color": "#d9902f"}, "yaxis": "y2", "opacity": 0.85},
            {"type": "scatter", "mode": "lines+markers", "name": "Precio medio (€/MWh)", "x": [x["corta"] for x in s],
             "y": _l([x["precio_medio"] for x in s]), "line": {"color": "#1f7a8c", "width": 3}},
        ],
        "layout": {"height": 270, "margin": {"l": 52, "r": 56, "t": 8, "b": 40},
                   "yaxis": {"title": {"text": "€/MWh"}},
                   "yaxis2": {"overlaying": "y", "side": "right", "showgrid": False, "title": {"text": "€/MW·día"}, "rangemode": "tozero"},
                   "legend": {"orientation": "h", "y": -0.22}},
    }

    # --- demanda
    d = res["demanda"]
    if d:
        idx = d["real"].index
        tv, tt = _eje_semana(idx)
        tr = [{"type": "scatter", "mode": "lines", "name": "Real", "x": list(range(len(idx))), "y": _l(d["real"].values),
               "line": {"color": "#10263a", "width": 2}}]
        if "prevista" in d:
            tr.append({"type": "scatter", "mode": "lines", "name": "Prevista", "x": list(range(len(idx))), "y": _l(d["prevista"].values),
                       "line": {"color": "#d9902f", "width": 1.5, "dash": "dot"}})
        ch["g_dem"] = {"data": tr, "layout": {"height": 270, "margin": {"l": 60, "r": 10, "t": 8, "b": 40},
                       "xaxis": {"tickvals": tv, "ticktext": tt}, "yaxis": {"title": {"text": "MW"}},
                       "legend": {"orientation": "h", "y": -0.22}}}

    # --- otros mercados
    if res["extras"]:
        idx = res["spot"].index
        tv, tt = _eje_semana(idx)
        tr = [{"type": "scatter", "mode": "lines", "name": "Mercado diario", "x": list(range(len(idx))), "y": _l(res["spot"].values),
               "line": {"color": "#10263a", "width": 2}}]
        for e in res["extras"]:
            tr.append({"type": "scatter", "mode": "lines", "name": e["nombre"], "x": list(range(len(idx))), "y": _l(e["serie"].values),
                       "line": {"width": 1.2}, "opacity": 0.8})
        ch["g_merc"] = {"data": tr, "layout": {"height": 330, "margin": {"l": 52, "r": 10, "t": 8, "b": 40},
                        "xaxis": {"tickvals": tv, "ticktext": tt}, "yaxis": {"title": {"text": "€/MWh"}},
                        "legend": {"orientation": "h", "y": -0.25}}}
    return ch


# Páginas del PDF que se muestran también en la web (lo esencial para almacenamiento), en este orden.
WEB_CLAVES = [
    "Señales de la semana",
    "Precio de la banda de aFRR",
    "Curva de duración",
    "Rango de precios de cada día",
    "¿Cuánto vale cada hora",
    "Arbitraje frente a reservar banda",
    "Dónde paga más cada mercado",
    "Precio capturado por tecnología y mercado",
    "Almacenamiento generación · energía",
    "Almacenamiento generación · precio",
    "Almacenamiento consumo · energía",
    "Almacenamiento consumo · precio",
    "Canibalización",
    "Qué mueve el precio",
]


def es_web(titulo):
    return bool(titulo) and any(titulo.startswith(k) for k in WEB_CLAVES)


def _esenciales(paginas):
    def clave(p):
        return next(i for i, k in enumerate(WEB_CLAVES) if (p["titulo"] or "").startswith(k))

    return sorted([p for p in paginas or [] if es_web(p["titulo"])], key=clave)


def render(res, cfg, meta, demo=False, base="", paginas=None, pdf_url=None, npag=None):
    textos = redactar(res)
    env = Environment(loader=FileSystemLoader(RAIZ / "templates"), autoescape=select_autoescape(["html", "j2"]))
    env.filters["n"] = n
    tpl = env.get_template("informe.html.j2")
    semana_num = int(res["etiqueta"].split("S")[1])
    return tpl.render(
        res=res, t=textos, charts=graficos(res), cfg=cfg, meta=meta, demo=demo,
        rango=rango(res), semana_num=semana_num, anio=res["etiqueta"].split("-")[0],
        generado=datetime.now().strftime("%d/%m/%Y %H:%M"),
        bat=cfg["bateria"], base=base,
        esenciales=_esenciales(paginas), npag=npag, pdf_url=pdf_url,
    )
