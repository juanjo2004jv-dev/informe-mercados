"""Punto de entrada.  python -m src.run --semana anterior   (o --demo para probar)"""
import argparse
import os
import shutil
import json
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

from . import analisis as A
from .informe import render
from .pdf import generar_pdf
from .narrativa import rango

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
TZ = A.TZ


def _sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _con_respaldo(cli, v, s, ini, fin):
    """Si la serie principal no cubre la semana y hay `respaldo`, completa los huecos con él.
    `max_valido` descarta DÍAS enteros del respaldo con valores imposibles (p. ej. desde el
    25-oct-2026 el 10388 deja de publicarse en €/MW y da cifras de decenas de miles)."""
    resp = v.get("respaldo")
    if not resp:
        return s, None
    rej = A.rejilla(ini, fin)
    cob = A.alinear(s, rej).notna().mean() if len(s) else 0.0
    if cob >= 0.95:
        return s, None
    try:
        _, r = cli.serie(resp, ini, fin, v.get("geo"))
    except Exception:
        return s, f"serie {v['id']} incompleta ({cob:.0%}) y sin respaldo disponible."
    descartados = []
    if len(r) and v.get("max_valido"):
        dia = pd.Series(r.index.tz_convert(TZ).date, index=r.index)
        malos = r.abs().groupby(dia).max()
        malos = set(malos[malos > v["max_valido"]].index)
        descartados = sorted(malos)
        r = r[~dia.isin(malos)]
    if not len(r):
        return s, (f"ESIOS no publica la serie {v['id']} en esta semana (cobertura {cob:.0%}) y el respaldo {resp} "
                   f"no da valores interpretables como €/MW: sin dato, no se estima.")
    s = r if not len(s) else s.combine_first(r)
    txt = f"la serie {v['id']} solo cubre el {cob:.0%} de la semana; huecos completados con la {resp}."
    if descartados:
        txt += f" Días sin dato válido (valores fuera de rango en la {resp}): {', '.join(d.strftime('%d-%m') for d in descartados)}."
    return s, txt


def descargar(cfg, lunes):
    from .esios import Esios

    cli = Esios()
    ini_base, _ = A.limites_semana(A.lunes_k(lunes, 4))
    _, fin = A.limites_semana(lunes)
    ini, _ = A.limites_semana(lunes)
    datos, meta = {}, {}
    todas = dict(cfg["series"])
    todas.update({k: v for k, v in cfg.get("opcionales", {}).items() if v.get("id")})
    for k, v in todas.items():
        desde = ini_base if (k == "spot" or k in ("gen_solar_fv", "gen_eolica")) else ini
        try:
            nombre_api, s = cli.serie(v["id"], desde, fin, v.get("geo"))
        except Exception as e:
            if k == "spot":
                raise
            meta[k] = {"nombre": v["nombre"], "id": v["id"], "api": "—", "aviso": f"no se pudo descargar ({e})"}
            continue
        m = {"nombre": v["nombre"], "id": v["id"], "api": nombre_api}
        s, aviso_resp = _con_respaldo(cli, v, s, desde, fin)
        if aviso_resp:
            m["aviso"] = aviso_resp
        datos[k] = s
        pal = v.get("palabras", [])
        if pal and not all(_sin_acentos(p) in _sin_acentos(nombre_api) for p in pal):
            m["aviso"] = (m.get("aviso", "") + " " if m.get("aviso") else "") + f"el indicador {v['id']} se llama «{nombre_api}»; comprueba que es la serie que quieres."
            if v.get("provisional"):
                m["aviso"] += " Serie descartada (ID provisional)."
                meta[k] = m
                datos.pop(k, None)
                continue
        meta[k] = m
    return datos, meta


def cargar_i3(lunes, res, demo):
    """Devuelve (i3_semana, i3_historico, mensajes). Si falla o no valida, (None, None, mensajes):
    el informe sale igual, sin las secciones basadas en I3."""
    from . import i3 as I

    dias = pd.date_range(lunes, lunes + timedelta(days=6))
    if demo:
        from .i3_demo import semana, historico

        pm = [res["medias_dia"].get(x.date(), 150) for x in dias]
        sem = semana(dias, pm)
        ok, msg = I.validar(sem)
        return sem, pd.concat([historico("2025-01-01", lunes - timedelta(days=1)), sem]), msg
    try:
        alm, fallos, _ = I.actualizar(date(2025, 1, 1), lunes + timedelta(days=6), maxdias=120)
    except Exception as e:
        return None, None, [f"I3 no disponible ({str(e)[:90]}). Se omiten las secciones basadas en I3."]
    f = pd.to_datetime(alm["fecha"]) if len(alm) else pd.Series([], dtype="datetime64[ns]")
    sem = alm[(f >= pd.Timestamp(lunes)) & (f <= pd.Timestamp(lunes + timedelta(days=6)))] if len(alm) else alm
    if sem["fecha"].nunique() < 7 if len(sem) else True:
        return None, None, [f"I3 incompleto para la semana ({sem['fecha'].nunique() if len(sem) else 0}/7 días publicados). Se omiten las secciones basadas en I3."]
    ok, msg = I.validar(sem)
    if not ok:
        return None, None, msg + ["Se omiten las secciones basadas en I3."]
    return sem, alm, msg


def actualizar_historial(res):
    ruta = RAIZ / "data" / "historial.json"
    hist = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    hist = [h for h in hist if h["etiqueta"] != res["etiqueta"]]
    hist.append(
        {
            "etiqueta": res["etiqueta"],
            "rango": rango(res),
            "precio_medio": round(res["precio_medio"], 2),
            "horas_neg": res["horas_neg"],
            "bess_dia": round(res["bess_dia"], 1),
            "spread_medio": round(res["spread_medio"], 1),
        }
    )
    hist.sort(key=lambda h: h["etiqueta"])
    ruta.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    return hist


def escribir_archivo(hist):
    filas = "\n".join(
        f'<li><a href="semanas/{h["etiqueta"]}.pdf">Semana {h["etiqueta"][-2:]} de {h["etiqueta"][:4]} (PDF)</a> · <a href="semanas/{h["etiqueta"]}.html">versión web</a> '
        f'<span>{h["rango"]} · {h["precio_medio"]:.1f} €/MWh · techo batería {h["bess_dia"]:.0f} €/MW·día</span></li>'
        for h in reversed(hist)
    )
    (DOCS / "archivo.html").write_text(
        '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Semanas anteriores</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:720px;margin:48px auto;padding:0 20px}"
        "li{margin:10px 0}span{display:block;color:#667;font-size:14px}</style>"
        f"<h1>Semanas anteriores</h1><p><a href=\"ultimo.pdf\">Último PDF</a> · <a href=\"index.html\">Última versión web</a></p><ul>{filas}</ul></html>",
        encoding="utf-8",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semana", default="anterior", help="'anterior' o una fecha AAAA-MM-DD de esa semana")
    ap.add_argument("--demo", action="store_true", help="datos sintéticos (no necesita token)")
    ap.add_argument("--force", action="store_true", help="regenerar aunque ya exista")
    ap.add_argument("--config", default=str(RAIZ / "config.yml"))
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    hoy = datetime.now(pd.Timestamp.now(tz=TZ).tzinfo).date()
    if a.semana == "anterior":
        ref = hoy - timedelta(days=7)
    else:
        ref = date.fromisoformat(a.semana)
    lunes = ref - timedelta(days=ref.weekday())
    if lunes + timedelta(days=7) > hoy and not a.demo:
        sys.exit(f"La semana que empieza el {lunes} aún no ha terminado.")
    iso = lunes.isocalendar()
    etiqueta = f"{iso.year}-S{iso.week:02d}"
    destino = DOCS / "demo.html" if a.demo else DOCS / "semanas" / f"{etiqueta}.html"
    if destino.exists() and not a.force and not a.demo:
        print(f"{etiqueta}: ya existe, nada que hacer.")
        return

    ini_base, _ = A.limites_semana(A.lunes_k(lunes, 4))
    _, fin = A.limites_semana(lunes)
    if a.demo:
        from .demo import generar

        datos, meta = generar(A.rejilla(ini_base, fin), cfg)
    else:
        datos, meta = descargar(cfg, lunes)

    res = A.analizar(datos, cfg, lunes)
    cob = res["cobertura"]["spot"]
    if cob < cfg["umbral_cobertura_spot"] and not a.force:
        sys.exit(f"Cobertura del precio spot insuficiente ({cob:.1%}). Se reintentará en la siguiente ejecución.")

    html = render(res, cfg, meta, demo=a.demo, base="" if a.demo else "../", pdf_url=f"{etiqueta}.pdf" if not a.demo else "demo.pdf")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding="utf-8")
    print(f"Generado {destino.relative_to(RAIZ)} (cobertura spot {cob:.1%})")
    i3, i3_hist, i3_estado = cargar_i3(lunes, res, a.demo)
    pdf = destino.with_suffix(".pdf")
    img_dir = None
    if not a.demo:
        img_dir = DOCS / "paginas"
        shutil.rmtree(img_dir, ignore_errors=True)
        img_dir.mkdir(parents=True, exist_ok=True)
    paginas, lista_pag = generar_pdf(res, cfg, meta, pdf, demo=a.demo, i3=i3, i3_hist=i3_hist, i3_estado=i3_estado, img_dir=img_dir)
    print(f"Generado {pdf.relative_to(RAIZ)} ({paginas} páginas)")
    if not a.demo:
        (DOCS / "index.html").write_text(render(res, cfg, meta, demo=False, base="", paginas=lista_pag, pdf_url="ultimo.pdf", npag=paginas), encoding="utf-8")
        shutil.copyfile(pdf, DOCS / "ultimo.pdf")
        escribir_archivo(actualizar_historial(res))
        salida = os.environ.get("GITHUB_OUTPUT")
        if salida:
            with open(salida, "a") as f:
                f.write(f"pdf={pdf.relative_to(RAIZ)}\n")


if __name__ == "__main__":
    main()
