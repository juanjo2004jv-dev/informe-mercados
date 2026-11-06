"""Lector de los ficheros I3 de REE (archivo ESIOS nº 32, "I3DIA").

Diseño en tres capas, para que nunca se publique un número dudoso:
  1. LECTURA genérica: cada hoja del libro se convierte a (etiquetas, suma diaria).
     No depende de nombres de hoja concretos, solo de que la hoja tenga columnas
     de texto seguidas de columnas numéricas por periodo (formato habitual de REE).
  2. CLASIFICACIÓN por palabras clave (src/i3_mapa.yml, editable) hacia una tabla
     ordenada: fecha, mercado, tecnologia, magnitud, fase, tipologia, sentido, valor.
  3. VALIDACIÓN: la cascada de programas debe cerrar contra el P48 publicado
     (la misma comprobación que UNEF declara). Si no cierra, las secciones I3
     se omiten y el informe lo dice, en lugar de publicar cifras erróneas.

Uso:
  python -m src.i3 --diagnostico 2026-10-20     # vuelca la estructura real del fichero
  python -m src.i3 --backfill 2025-01-01        # descarga el histórico (una vez)
  (el informe semanal completa solo los días que falten)
"""
import argparse
import io
import json
import re
import sys
import unicodedata
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parent.parent
ALMACEN = RAIZ / "data" / "i3_diario.csv.gz"
MAPA = RAIZ / "src" / "i3_mapa.yml"
COLS = ["fecha", "mercado", "tecnologia", "magnitud", "fase", "tipologia", "sentido", "valor"]
ARCHIVO_I3 = 32


def sin(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn").strip()


# ----------------------------------------------------------------- 1. lectura genérica
def _periodo(v):
    """¿Es la cabecera de un periodo (1..100, o una hora 00:15)?"""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and not np.isnan(v):
        return float(v).is_integer() and 1 <= int(v) <= 100
    s = str(v).strip()
    return bool(re.fullmatch(r"\d{1,3}", s) or re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s))


def leer_hoja(filas):
    """filas: lista de listas. Devuelve [(etiquetas[tuple], suma, vector)] o []."""
    cab = None
    for i, f in enumerate(filas[:40]):
        cuenta = sum(_periodo(v) for v in f)
        if cuenta >= 20:
            cab = i
            break
    if cab is None:
        return []
    f0 = filas[cab]
    ini = next(j for j, v in enumerate(f0) if _periodo(v))
    out = []
    contexto = [""] * ini
    for f in filas[cab + 1:]:
        if len(f) <= ini:
            continue
        et = [("" if v is None else str(v).strip()) for v in f[:ini]]
        for j, v in enumerate(et):               # celdas combinadas: heredar
            if v:
                contexto[j] = v
                for k in range(j + 1, ini):
                    contexto[k] = et[k] if et[k] else ""
            else:
                et[j] = contexto[j]
        nums = [v for v in f[ini:] if isinstance(v, (int, float)) and not isinstance(v, bool) and not np.isnan(v)]
        if not nums or not any(et):
            continue
        vec = np.array([v if isinstance(v, (int, float)) and not isinstance(v, bool) and not np.isnan(v) else 0.0 for v in f[ini:]], dtype=float)
        out.append((tuple(et), float(sum(nums)), vec))
    return out


def abrir_libro(contenido, nombre="x.xls"):
    from python_calamine import CalamineWorkbook

    suf = Path(nombre).suffix.lower()
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=suf or ".xls", delete=False) as t:
        t.write(contenido)
        ruta = t.name
    wb = CalamineWorkbook.from_path(ruta)
    return {n: wb.get_sheet_by_name(n).to_python() for n in wb.sheet_names}


def hojas_de_zip(contenido):
    z = zipfile.ZipFile(io.BytesIO(contenido))
    for n in z.namelist():
        if n.lower().endswith((".xls", ".xlsx", ".xlsm")):
            return abrir_libro(z.read(n), n)
    raise RuntimeError("El zip del I3 no contiene ningún Excel")


def descripcion_hojas(hojas):
    """La primera hoja es un índice: nombre de hoja -> descripción."""
    desc = {}
    primera = next(iter(hojas.values()))
    for f in primera:
        celdas = [str(c).strip() for c in f if c not in (None, "")]
        if len(celdas) >= 2 and re.match(r"^I3\w*\d", celdas[0], re.I):
            desc[celdas[0]] = celdas[1]
    return desc


# ----------------------------------------------------------------- 2. clasificación
def cargar_mapa():
    return yaml.safe_load(open(MAPA, encoding="utf-8"))


def _contiene(txt, kws):
    return any(k in txt for k in kws)


def clasificar(hoja, desc, etiquetas, mapa):
    """Devuelve dict con mercado/tecnologia/magnitud/fase/tipologia/sentido o None."""
    texto = sin(" ".join([desc] + list(etiquetas)))
    r = {"mercado": None, "tecnologia": "", "magnitud": None, "fase": "", "tipologia": "", "sentido": ""}
    for nombre, kws in mapa["mercados"].items():            # el orden del YAML importa
        if _contiene(texto, [sin(k) for k in kws]):
            r["mercado"] = nombre
            break
    for nombre, kws in mapa["magnitudes"].items():
        if _contiene(texto, [sin(k) for k in kws]):
            r["magnitud"] = nombre
            break
    etiq = [sin(e) for e in etiquetas]
    for tec, kws in mapa["tecnologias"].items():
        if any(e == sin(k) or sin(k) in e for e in etiq for k in kws):
            r["tecnologia"] = tec
            break
    for f, kws in mapa["fases"].items():
        if _contiene(texto, [sin(k) for k in kws]):
            r["fase"] = f
            break
    for t in mapa["tipologias"]:
        if any(re.search(rf"\b{t.lower()}\b", e) for e in etiq):
            r["tipologia"] = t
            break
    if _contiene(texto, ["subir", "a subir", "ascendente"]):
        r["sentido"] = "Subir"
    elif _contiene(texto, ["bajar", "a bajar", "descendente"]):
        r["sentido"] = "Bajar"
    if not r["mercado"] or not r["magnitud"]:
        return None
    return r


def _x_spot(vec, spot):
    """Σ energía·precio con el precio spot del mismo periodo (cuartohorario u horario)."""
    if spot is None or len(spot) == 0:
        return None
    n, m = len(vec), len(spot)
    sp = np.asarray(spot, float)
    if n != m:
        if m % n == 0:
            sp = sp.reshape(n, m // n).mean(axis=1)
        elif n % m == 0:
            sp = np.repeat(sp, n // m)
        else:
            return None
    return float(np.nansum(vec * sp))


def procesar_libro(hojas, dia, mapa, spot=None):
    desc = descripcion_hojas(hojas)
    filas, sin_clasificar = [], {}
    for nombre, datos in hojas.items():
        d = desc.get(nombre, nombre)
        try:
            leidas = leer_hoja(datos)
        except Exception as e:                                # una hoja rota no tumba el día
            sin_clasificar[f"{nombre} (error {e})"] = 0
            continue
        for et, suma, vec in leidas:
            c = clasificar(nombre, d, et, mapa)
            if c is None:
                sin_clasificar[nombre] = sin_clasificar.get(nombre, 0) + 1
                continue
            filas.append({"fecha": dia, **c, "valor": suma})
            if c["mercado"] == "Restricciones MD" and c["magnitud"] == "energia" and c["tipologia"] in ("COT", "SOT") and c["sentido"] == "Subir":
                xs = _x_spot(vec, spot)
                if xs is not None:
                    filas.append({"fecha": dia, **{**c, "magnitud": "energia_x_spot"}, "valor": xs})
    df = pd.DataFrame(filas, columns=COLS)
    if len(df):
        df = df.groupby(["fecha", "mercado", "tecnologia", "magnitud", "fase", "tipologia", "sentido"], as_index=False)["valor"].sum()
    return df, sin_clasificar


# ----------------------------------------------------------------- descarga + almacén
def descargar_dia(cli, dia):
    """Descarga el I3 de un día vía la API de ESIOS. Devuelve bytes del zip."""
    d = dia.isoformat()
    j = cli._get(f"/archives/{ARCHIVO_I3}", {"date_type": "datos", "start_date": d + "T00:00:00", "end_date": d + "T23:59:59", "locale": "es"})
    url = j["archive"]["download"]["url"]
    r = cli.s.get("https://api.esios.ree.es" + url, timeout=180)
    r.raise_for_status()
    return r.content


def cargar_almacen():
    if ALMACEN.exists():
        return pd.read_csv(ALMACEN, parse_dates=["fecha"], keep_default_na=False, na_values=[""]).assign(
            fase=lambda d: d["fase"].fillna(""), tipologia=lambda d: d["tipologia"].fillna(""), sentido=lambda d: d["sentido"].fillna(""), tecnologia=lambda d: d["tecnologia"].fillna("")
        )
    return pd.DataFrame(columns=COLS)


def guardar_almacen(df):
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.strftime("%Y-%m-%d")
    df.sort_values(["fecha", "mercado", "tecnologia"]).to_csv(ALMACEN, index=False, compression="gzip")


def spot_dia(cli, dia):
    """Precio spot (indicador 600) del día, cuartohorario, hora local."""
    import pandas as _pd

    ini = _pd.Timestamp(dia).tz_localize("Europe/Madrid")
    fin = _pd.Timestamp(dia + timedelta(days=1)).tz_localize("Europe/Madrid")
    _, s = cli.serie(600, ini, fin, [3, 8741])
    return s.values if len(s) else None


def actualizar(desde, hasta, cli=None, maxdias=None):
    """Completa el almacén con los días que falten entre desde y hasta."""
    from .esios import Esios

    cli = cli or Esios()
    mapa = cargar_mapa()
    alm = cargar_almacen()
    tengo = set(pd.to_datetime(alm["fecha"]).dt.date) if len(alm) else set()
    nuevos, fallos, sc_total = [], [], {}
    dia = desde
    hechos = 0
    while dia <= hasta:
        if dia not in tengo:
            try:
                hojas = hojas_de_zip(descargar_dia(cli, dia))
                try:
                    sp = spot_dia(cli, dia)
                except Exception:
                    sp = None
                df, sc = procesar_libro(hojas, pd.Timestamp(dia), mapa, sp)
                if len(df):
                    nuevos.append(df)
                for k, v in sc.items():
                    sc_total[k] = sc_total.get(k, 0) + v
                hechos += 1
            except Exception as e:                              # día aún no publicado, etc.
                fallos.append((dia.isoformat(), str(e)[:80]))
            if maxdias and hechos >= maxdias:
                break
        dia += timedelta(days=1)
    if nuevos:
        alm = pd.concat([alm] + nuevos, ignore_index=True)
        guardar_almacen(alm)
    return alm, fallos, sc_total


# ----------------------------------------------------------------- 3. validación
PROGRAMAS = ["PBF", "PDVP", "PHF", "P48"]


def cascada(df, tec=None):
    """Cascada de programas para el periodo df (ya filtrado por fechas)."""
    e = df[df["magnitud"] == "energia"]
    if tec:
        e = e[e["tecnologia"] == tec]

    def s(mercados, sentido=None, tip=None):
        x = e[e["mercado"].isin(mercados)]
        if sentido:
            x = x[x["sentido"] == sentido]
        return float(x["valor"].sum())

    prog = {p: float(e[e["mercado"] == p]["valor"].sum()) for p in PROGRAMAS}
    c = {
        "diario": s(["Diario"]),
        "bilaterales": s(["Bilaterales"]),
        "pbf": prog["PBF"],
        "restr_pbf_sub": s(["Restricciones MD"], "Subir"),
        "restr_pbf_baj": s(["Restricciones MD"], "Bajar"),
        "pdvp": prog["PDVP"],
        "ida_sub": s(["Intradiario 1", "Intradiario 2", "Intradiario 3", "Continuo"], "Subir"),
        "ida_baj": s(["Intradiario 1", "Intradiario 2", "Intradiario 3", "Continuo"], "Bajar"),
        "phf": prog["PHF"],
        "restr_tr_sub": s(["Restricciones TR"], "Subir"),
        "restr_tr_baj": s(["Restricciones TR"], "Bajar"),
        "post_tr": 0.0,
        "terc_sub": s(["Terciaria"], "Subir"),
        "terc_baj": s(["Terciaria"], "Bajar"),
        "p48": prog["P48"],
    }
    calc = c["pbf"] + c["restr_pbf_sub"] + c["restr_pbf_baj"] + c["ida_sub"] + c["ida_baj"] + c["restr_tr_sub"] + c["restr_tr_baj"] + c["terc_sub"] + c["terc_baj"]
    c["p48_calculado"] = calc
    c["dif_pct"] = abs(calc - c["p48"]) / abs(c["p48"]) * 100 if c["p48"] else np.nan
    return c


def validar(df, tol_pct=0.5):
    """(ok, mensajes). Puerta de calidad antes de publicar nada de I3."""
    msgs = []
    if df is None or len(df) == 0:
        return False, ["No hay datos I3 para el periodo."]
    c = cascada(df)
    if c["p48"] == 0 or c["pbf"] == 0:
        msgs.append("No se identificaron los programas PBF/P48 en el I3 (revisar src/i3_mapa.yml).")
        return False, msgs
    if not (c["dif_pct"] <= tol_pct):
        msgs.append(f"La cascada de programas no cierra contra el P48 ({c['dif_pct']:.2f} % de diferencia).")
        return False, msgs
    return True, [f"Cascada cerrada contra el P48 con {c['dif_pct']:.2f} % de diferencia."]


# ----------------------------------------------------------------- diagnóstico
def diagnostico(dia):
    from .esios import Esios

    cli = Esios()
    hojas = hojas_de_zip(descargar_dia(cli, dia))
    desc = descripcion_hojas(hojas)
    mapa = cargar_mapa()
    out = [f"I3 del {dia}: {len(hojas)} hojas\n"]
    for n, datos in hojas.items():
        leidas = leer_hoja(datos)
        out.append(f"=== {n} · {desc.get(n, '')} · {len(leidas)} filas con datos")
        for et, suma, _v in leidas[:6]:
            c = clasificar(n, desc.get(n, n), et, mapa)
            out.append(f"   {et} -> suma {suma:,.1f}  => {c}")
    ruta = RAIZ / "data" / "i3_estructura.txt"
    ruta.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:80]))
    print(f"\nGuardado en {ruta}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostico", help="AAAA-MM-DD: vuelca la estructura del I3 de ese día")
    ap.add_argument("--backfill", help="AAAA-MM-DD: descarga el histórico desde esa fecha")
    ap.add_argument("--maxdias", type=int, default=None)
    a = ap.parse_args()
    if a.diagnostico:
        diagnostico(date.fromisoformat(a.diagnostico))
    elif a.backfill:
        alm, fallos, sc = actualizar(date.fromisoformat(a.backfill), date.today() - timedelta(days=3), maxdias=a.maxdias)
        print(f"Almacén: {len(alm)} filas, {alm['fecha'].nunique() if len(alm) else 0} días. Fallos: {len(fallos)}. Hojas sin clasificar: {sc}")
        for f in fallos[:10]:
            print("  fallo", f)
    else:
        ap.print_help()
