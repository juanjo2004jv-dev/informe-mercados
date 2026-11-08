"""Punto de entrada.  python -m src.run --semana anterior   (o --demo para probar)"""
import argparse
import os
import shutil
import json
import sys
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
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
    txt = f"la serie {v['id']} solo cubre el {cob:.0%} de la semana"
    if len(r):
        s = r if not len(s) else s.combine_first(r)
        if (A.alinear(s, rej).notna().mean() if len(s) else 0.0) > cob + 0.005:
            txt += f"; huecos completados con la {resp}"
    if descartados:
        txt += f"; la {resp} publica esos días el coste en € y no el precio (se descarta)"
    est = v.get("estimar")
    cob2 = A.alinear(s, rej).notna().mean() if len(s) else 0.0
    if est and cob2 < 0.95:
        # último recurso, VERIFICADO contra los días con dato: coste de la reserva (€) = precio (€/MW) ×
        # banda asignada (MW). Sin la asignada se divide por la requerida: error medio < 1 % (5-8 nov 2026).
        try:
            _, coste = cli.serie(est["coste"], ini, fin)
            _, banda = cli.serie(est["banda"], ini, fin)
            e = (coste / banda.replace(0, float("nan"))).dropna()
            e = e[(e >= -1) & (e <= v.get("max_valido", 1e9))]
            if len(e):
                hueco = A.alinear(s, rej).isna() if len(s) else pd.Series(True, index=rej)
                dias_est = sorted(set(e.index[e.index.isin(rej[hueco])].tz_convert(TZ).date))
                s = e if not len(s) else s.combine_first(e)
                if dias_est:
                    txt += (f"; los días {', '.join(d.strftime('%d-%m') for d in dias_est)} se ESTIMAN como coste de la reserva (ID {est['coste']}) ÷ "
                            f"banda requerida (ID {est['banda']}), con un error medio inferior al 1 % frente al dato oficial")
        except Exception as ex:
            txt += f"; no se pudo estimar ({str(ex)[:60]})"
    return s, txt + "."


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
    # mix de generación y balance (baterías, bombeo, intercambios): solo la semana; si falla, se omite
    for grupo, pref in (("mix", "mix_"), ("balance", "bal_")):
        for k, v in (cfg.get(grupo) or {}).items():
            try:
                _, s = cli.serie(v["id"], ini, fin, v.get("geo"))
                datos[pref + k] = s
            except Exception as e:
                meta[pref + k] = {"nombre": v["nombre"], "id": v["id"], "api": "—", "aviso": f"no se pudo descargar ({str(e)[:80]})"}
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
        ndias = sem["fecha"].nunique() if len(sem) else 0
        # edición del lunes: el I3 de la semana llega a D+4. Para que el PDF salga entero, las secciones
        # de I3 usan la ÚLTIMA SEMANA COMPLETA (la anterior), rotulada como tal; el informe se regenera
        # solo con el I3 de la semana en cuanto REE lo complete.
        la, lb = pd.Timestamp(lunes - timedelta(days=7)), pd.Timestamp(lunes - timedelta(days=1))
        ant = alm[(f >= la) & (f <= lb)] if len(alm) else alm
        if len(ant) and ant["fecha"].nunique() >= 7:
            ok, msg = I.validar(ant)
            if ok:
                hist = alm[f <= lb]
                msg = [f"I3 de esta semana incompleto ({ndias}/7 días publicados): las secciones de I3 usan la semana anterior "
                       f"({la.date()} a {lb.date()}) y se actualizarán solas."] + msg
                return ant, hist, msg
        return None, None, [f"I3 incompleto para la semana ({ndias}/7 días publicados). Se omiten las secciones basadas en I3."]
    ok, msg = I.validar(sem)
    if not ok:
        return None, None, msg + ["Se omiten las secciones basadas en I3."]
    huecos = I.huecos_precios(sem)
    if huecos:
        msg = msg + [f"REE publicó el I3 de {', '.join(d.strftime('%d-%m') for d in huecos)} sin las hojas de precios de restricciones: "
                     "esos días la energía es correcta pero el coste sale vacío. El informe se regenera solo si REE las completa."]
    hist = alm[f <= pd.Timestamp(lunes + timedelta(days=6))]       # el histórico acaba con la semana del informe
    return sem, hist, msg


def estado_i3(lunes):
    """(días de la semana en el almacén, días con huecos de precios). Descarga lo que falte."""
    from . import i3 as I

    try:
        alm, _, _ = I.actualizar(date(2025, 1, 1), lunes + timedelta(days=6), maxdias=120)
    except Exception as e:
        print(f"I3: no se pudo actualizar ({str(e)[:120]})")
        return 0, []
    if not len(alm):
        return 0, []
    f = pd.to_datetime(alm["fecha"])
    sem = alm[(f >= pd.Timestamp(lunes)) & (f <= pd.Timestamp(lunes + timedelta(days=6)))]
    return sem["fecha"].nunique(), I.huecos_precios(sem)


def i3_completo(lunes):
    """True si el I3 de los 7 días de la semana ya está en el almacén (descarga lo que falte)."""
    return estado_i3(lunes)[0] >= 7


def _lunes_de(etiqueta):
    a, s = etiqueta.split("-S")
    return date.fromisocalendar(int(a), int(s), 1).isoformat()


def leer_historial():
    ruta = RAIZ / "data" / "historial.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []


def actualizar_historial(res, completo, paginas, huecos=None):
    ruta = RAIZ / "data" / "historial.json"
    hist = [h for h in leer_historial() if h["etiqueta"] != res["etiqueta"]]
    hist.append(
        {
            "etiqueta": res["etiqueta"],
            "lunes": res["lunes"].isoformat(),
            "rango": rango(res),
            "precio_medio": round(res["precio_medio"], 2),
            "horas_neg": res["horas_neg"],
            "bess_dia": round(res["bess_dia"], 1),
            "spread_medio": round(res["spread_medio"], 1),
            "completo": bool(completo),
            "i3_huecos": [str(x) for x in (huecos or [])],
            "paginas": int(paginas),
            "generado": datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M"),
        }
    )
    hist.sort(key=lambda h: h["etiqueta"])
    ruta.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    return hist


def escribir_archivo(hist):
    filas = "\n".join(
        f'<li><a href="semanas/{h["etiqueta"]}.pdf">Semana {h["etiqueta"][-2:]} de {h["etiqueta"][:4]} (PDF)</a> · <a href="semanas/{h["etiqueta"]}.html">versión web</a> '
        f'<span>{h["rango"]} · {h["precio_medio"]:.1f} €/MWh · techo batería {h["bess_dia"]:.0f} €/MW·día'
        f'{"" if h.get("completo", True) else " · provisional, sin I3"}</span></li>'
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
    ap.add_argument("--ensayo", action="store_true",
                    help="prueba con datos reales SIN publicar: admite la semana en curso y escribe en data/ensayo/")
    ap.add_argument("--config", default=str(RAIZ / "config.yml"))
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    hoy = datetime.now(pd.Timestamp.now(tz=TZ).tzinfo).date()
    if a.semana == "pendientes":
        # semanas ya publicadas cuyo I3 salió con días sin precios: se reintentan durante 4 semanas
        cand = [h for h in leer_historial() if h.get("i3_huecos")
                and (hoy - date.fromisoformat(h.get("lunes") or _lunes_de(h["etiqueta"]))).days <= 28]
        if not cand:
            print("Sin semanas pendientes de precios del I3.")
            return
        a.semana = (h := cand[-1]).get("lunes") or _lunes_de(h["etiqueta"])
        print(f"Revisando {h['etiqueta']} (días sin precios: {', '.join(h['i3_huecos'])}).")
    if a.semana == "anterior":
        ref = hoy - timedelta(days=7)
    elif a.semana == "actual":
        ref = hoy
    else:
        ref = date.fromisoformat(a.semana)
    lunes = ref - timedelta(days=ref.weekday())
    if lunes + timedelta(days=7) > hoy and not (a.demo or a.ensayo):
        sys.exit(f"La semana que empieza el {lunes} aún no ha terminado.")
    iso = lunes.isocalendar()
    etiqueta = f"{iso.year}-S{iso.week:02d}"
    if a.demo:
        destino = DOCS / "demo.html"
    elif a.ensayo:
        destino = RAIZ / "data" / "ensayo" / f"{etiqueta}.html"
    else:
        destino = DOCS / "semanas" / f"{etiqueta}.html"
    previo = next((h for h in leer_historial() if h["etiqueta"] == etiqueta), None)
    if destino.exists() and not a.force and not a.demo and not a.ensayo:
        pendiente_huecos = bool(previo and previo.get("i3_huecos")) and (hoy - lunes).days <= 28
        if previo is None or (previo.get("completo", True) and not pendiente_huecos):
            print(f"{etiqueta}: ya existe y está completo, nada que hacer.")
            return
        ndias, huecos = estado_i3(lunes)
        if not previo.get("completo", True):
            # el lunes sale provisional (el I3 llega a D+4): se rehace cuando el I3 de la semana está entero
            if ndias < 7:
                print(f"{etiqueta}: publicado como provisional; I3 de la semana con {ndias}/7 días. Se reintentará.")
                return
            print(f"{etiqueta}: el I3 ya está completo; se regenera el informe con todas las secciones.")
        else:
            # completo pero con días sin precios de restricciones: se rehace cuando REE los publica
            if set(map(str, huecos)) >= set(previo.get("i3_huecos", [])):
                print(f"{etiqueta}: completo; REE aún no ha publicado los precios de {', '.join(previo['i3_huecos'])}.")
                return
            print(f"{etiqueta}: REE ha completado precios del I3 que faltaban; se regenera el informe.")

    ini_base, _ = A.limites_semana(A.lunes_k(lunes, 4))
    _, fin = A.limites_semana(lunes)
    if a.demo:
        from .demo import generar

        datos, meta = generar(A.rejilla(ini_base, fin), cfg)
    else:
        datos, meta = descargar(cfg, lunes)

    res = A.analizar(datos, cfg, lunes)
    cob = res["cobertura"]["spot"]
    if cob < cfg["umbral_cobertura_spot"] and not (a.force or a.ensayo):
        sys.exit(f"Cobertura del precio spot insuficiente ({cob:.1%}). Se reintentará en la siguiente ejecución.")

    i3, i3_hist, i3_estado = cargar_i3(lunes, res, a.demo)
    i3_anterior = i3 is not None and pd.to_datetime(i3["fecha"]).min().date() < lunes
    res["provisional"] = i3 is None or i3_anterior
    res["i3_anterior"] = i3_anterior
    res["i3_estado"] = i3_estado
    res["i3_resumen"] = resumen_i3(i3) if (i3 is not None and not i3_anterior) else None
    from .i3 import huecos_precios

    res["i3_huecos"] = huecos_precios(i3) if (i3 is not None and not res["i3_anterior"]) else []
    from . import historico as Hs

    try:
        hs = Hs.actualizar(res, cfg, guardar=not (a.demo or a.ensayo))
        res["historico"] = hs
        res["comparativa"] = Hs.comparativa(hs, lunes)
    except Exception as e:
        print(f"AVISO: histórico omitido ({type(e).__name__}: {str(e)[:100]})")
        res["historico"], res["comparativa"] = None, None
    pdf = destino.with_suffix(".pdf")
    img_dir = None
    if not a.demo:
        # imágenes de la web en una carpeta por semana: la versión web archivada de cada semana
        # enseña SUS diapositivas, no las de la última
        img_dir = (destino.parent if a.ensayo else DOCS) / "paginas" / etiqueta
        shutil.rmtree(img_dir, ignore_errors=True)
        img_dir.mkdir(parents=True, exist_ok=True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    paginas, lista_pag = generar_pdf(res, cfg, meta, pdf, demo=a.demo, i3=i3, i3_hist=i3_hist, i3_estado=i3_estado, img_dir=img_dir)
    if img_dir is not None:
        lista_pag = [dict(p, img=f"{etiqueta}/{p['img']}") for p in lista_pag]
        if not a.ensayo:
            for viejo in (DOCS / "paginas").glob("*.*"):     # formato antiguo (todas las semanas en la misma carpeta)
                viejo.unlink()
    print(f"Generado {pdf.relative_to(RAIZ)} ({paginas} páginas, {('provisional, I3 de la semana anterior' if res.get('i3_anterior') else 'provisional sin I3') if res['provisional'] else 'completo con I3'})")
    html = render(res, cfg, meta, demo=a.demo, base="" if (a.demo or a.ensayo) else "../", paginas=lista_pag,
                  pdf_url=f"{etiqueta}.pdf" if not a.demo else "demo.pdf", npag=paginas)
    destino.write_text(html, encoding="utf-8")
    print(f"Generado {destino.relative_to(RAIZ)} (cobertura spot {cob:.1%})")
    _resumen_ejecucion(res, meta, paginas, pdf, a.ensayo)
    if a.ensayo:
        return
    if not a.demo:
        ultima = max([h["etiqueta"] for h in leer_historial()] + [etiqueta])
        if etiqueta >= ultima:          # rehacer una semana antigua no pisa la portada de la web
            (DOCS / "index.html").write_text(render(res, cfg, meta, demo=False, base="", paginas=lista_pag, pdf_url="ultimo.pdf", npag=paginas), encoding="utf-8")
            shutil.copyfile(pdf, DOCS / "ultimo.pdf")
        else:
            print(f"{etiqueta} no es la última semana publicada ({ultima}): no se toca index.html ni ultimo.pdf.")
        escribir_archivo(actualizar_historial(res, not res["provisional"], paginas, res.get("i3_huecos")))
        salida = os.environ.get("GITHUB_OUTPUT")
        if salida:
            with open(salida, "a") as f:
                f.write(f"pdf={pdf.relative_to(RAIZ)}\n")
                f.write(f"estado={'provisional' if res['provisional'] else 'completo'}\n")


def _resumen_ejecucion(res, meta, paginas, pdf, ensayo):
    """Resumen legible en el log y en la página del workflow (GITHUB_STEP_SUMMARY)."""
    lin = [f"## {'Ensayo' if ensayo else 'Informe'} {res['etiqueta']} · {rango(res)}",
           f"- PDF: `{pdf.relative_to(RAIZ)}` · {paginas} páginas · {('provisional (I3 de la semana anterior)' if res.get('i3_anterior') else 'provisional (sin I3)') if res['provisional'] else 'completo con I3'}",
           f"- Precio medio {res['precio_medio']:.1f} €/MWh · techo arbitraje 4 h {res['bess_dia']:.0f} €/MW·día · cobertura spot {res['cobertura']['spot']:.1%}"]
    baja = [f"{meta.get(k, {}).get('nombre', k)} ({c:.0%})" for k, c in res["cobertura"].items() if c < 0.9 and k not in ("ida3", "casada_ida3")]
    if baja:
        lin.append("- Series con cobertura < 90 %: " + ", ".join(baja))
    for m in res.get("i3_estado") or []:
        lin.append(f"- I3: {m}")
    for e in res.get("_errores_pdf") or []:
        lin.append(f"- ⚠ Página omitida: {e}")
    txt = "\n".join(lin)
    print(txt)
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(txt + "\n")


def resumen_i3(i3):
    """Cifras del almacenamiento según la liquidación (I3) de la semana."""
    out = {}
    for tec in ("Almacenamiento generación", "Almacenamiento consumo"):
        x = i3[i3["tecnologia"] == tec]
        e = x[x["magnitud"] == "energia"]
        ing = x[x["magnitud"] == "ingreso"]
        merc = [m for m in ("Diario", "Intradiario 1", "Intradiario 2", "Intradiario 3", "Continuo", "Restricciones MD", "Restricciones TR", "Terciaria")]
        out[tec] = {
            "p48_mwh": float(e[e["mercado"] == "P48"]["valor"].sum()),
            "pbf_mwh": float(e[e["mercado"] == "PBF"]["valor"].sum()),
            "ingreso": float(ing[ing["mercado"].isin(merc)]["valor"].sum()),
            "ingreso_mercado": {m: float(ing[ing["mercado"] == m]["valor"].sum()) for m in merc if (ing["mercado"] == m).any()},
        }
    g, c = out["Almacenamiento generación"], out["Almacenamiento consumo"]
    out["neto"] = g["ingreso"] + c["ingreso"]
    out["precio_venta"] = g["ingreso"] / g["p48_mwh"] if g["p48_mwh"] > 0 else float("nan")
    out["precio_compra"] = -c["ingreso"] / -c["p48_mwh"] if c["p48_mwh"] < 0 else float("nan")
    return out


if __name__ == "__main__":
    main()
