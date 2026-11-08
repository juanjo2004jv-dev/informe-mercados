"""Lector del I3 REAL de REE (21 CSV por día: I3DIA00..I3DIA20).

Hojas que usamos (estructura verificada con el fichero del 2026-10-28):
  14 PDBF (Mercado / Bilateral)      -> PBF, Diario, Bilaterales
  01 PDVP                            -> programa viable
  03 Restricciones técnicas PDBF     -> Fase I (UPOPV*/UPLPV*) y Fase II (ECO*)  [energía]
  09 Precios de esas restricciones   -> ingreso = energía x precio, periodo a periodo
  13 PHF-1..PHF-k                    -> programas tras cada sesión intradiaria
  18 PHFC                            -> programa tras el mercado continuo
  08 Restricciones tiempo real       -> UPOTROR/UPLTROR (+ DESCOM2, INDIS, ACCBAL como «Otros»)
  10 Precios restricciones TR
  07 Terciaria (energía)  16 Terciaria (precios)
  02 P48
Los intradiarios no vienen como hoja propia: su energía es la diferencia entre programas
(PHF-k menos el anterior, solo en los periodos que cubre cada sesión).
"""
import re

import numpy as np
import pandas as pd

from .i3 import cargar_mapa, sin

FASE1, FASE2, TRF = "MD · Fase I", "MD · Fase II", "Tiempo real"


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and np.isnan(v))


def _periodo_cab(c):
    try:
        x = float(str(c).strip().replace(",", "."))
    except ValueError:
        return None
    return int(x) if x.is_integer() and 1 <= x <= 100 else None


def leer(filas, n=None):
    """-> lista de (dict etiquetas por cabecera, vector periodos con NaN). Cabecera: fila con 'Total'.

    Cada valor se coloca en el periodo que dice SU cabecera, no por posición: algunas hojas
    (p. ej. la 10, precios de restricciones en tiempo real) omiten los periodos sin precio
    (cabecera «...;11;12;29;30;...») y leerlas por posición desalineaba todo el día.
    `n`: longitud del vector (periodos del día); por defecto, el mayor periodo de la cabecera."""
    cab = None
    for i, f in enumerate(filas[:15]):
        if any(str(c).strip() == "Total" for c in f):
            cab = i
            break
    if cab is None:
        return []
    h = [str(c).strip() for c in filas[cab]]
    it = h.index("Total")
    cols = [(j, _periodo_cab(h[j])) for j in range(it + 1, len(h))]
    cols = [(j, p) for j, p in cols if p]
    if not cols:
        return []
    maxp = max(p for _, p in cols)
    # hojas cuartohorarias (más de 25 periodos) se rellenan hasta los periodos del día; una
    # hoja horaria (<= 25) conserva los suyos aunque el día sea cuartohorario
    n = max(n, maxp) if (n and maxp > 25) else maxp
    out = []
    for f in filas[cab + 1:]:
        if len(f) <= it:
            continue
        lab = {h[j]: ("" if f[j] is None else str(f[j]).strip()) for j in range(it) if h[j]}
        if not any(lab.values()):
            continue
        vec = np.full(n, np.nan)
        for j, p in cols:
            if j < len(f) and _num(f[j]):
                vec[p - 1] = float(f[j])
        if np.all(np.isnan(vec)):
            continue
        out.append((lab, vec))
    return out


def periodos_dia(hojas):
    """Cuartos de hora del día según las cabeceras de las hojas cuartohorarias (92/96/100);
    None si todas son horarias."""
    n = 0
    for nombre in ("I3DIA01", "I3DIA02", "I3DIA13", "I3DIA14", "I3DIA03", "I3DIA18"):
        filas = hojas.get(nombre) or []
        for f in filas[:15]:
            if any(str(c).strip() == "Total" for c in f):
                ps = [p for p in (_periodo_cab(c) for c in f) if p]
                if ps and max(ps) > 25:
                    n = max(n, max(ps))
                break
    return n or None


def vector_precio(serie, dia, n):
    """Precio ESIOS (Serie con índice UTC, cuartohoraria u horaria) colocado en los n periodos
    del día del I3 por FECHA Y HORA, no por posición. Antes se usaba el vector tal cual: el
    ESIOS devolvía 97 valores (fin inclusivo) y el diario nunca se valoraba, y el IDA3 (solo
    12:00-24:00, 48 valores) se estiraba repitiendo cada precio dos veces sobre el día entero."""
    if serie is None:
        return None
    if not isinstance(serie, pd.Series):
        v = np.asarray(serie, float)
        return v if len(v) == n else None
    if not len(serie) or not n:
        return None
    ini = pd.Timestamp(dia).tz_localize("Europe/Madrid").tz_convert("UTC")
    fin = (pd.Timestamp(dia) + pd.Timedelta(days=1)).tz_localize("Europe/Madrid").tz_convert("UTC")
    paso = (fin - ini) / n
    idx = ini + paso * np.arange(n)
    s = serie[~serie.index.duplicated()].sort_index()
    s = s[(s.index >= ini - pd.Timedelta(hours=1)) & (s.index < fin)]
    if not len(s):
        return None
    if paso >= pd.Timedelta(minutes=59):                    # I3 horario: media de los cuartos de cada hora
        return np.array([s[(s.index >= t) & (s.index < t + paso)].mean() for t in idx], dtype=float)
    v = s.reindex(idx)
    paso_s = s.index.to_series().diff().median() if len(s) > 1 else pd.Timedelta(minutes=15)
    if paso_s >= pd.Timedelta(minutes=59):                  # serie horaria (continuo): se repite en sus cuartos
        v = v.fillna(s.reindex(idx, method="ffill", tolerance=pd.Timedelta(minutes=59)))
    return v.to_numpy(dtype=float)


class Tec:
    def __init__(self, mapa):
        self.kw = sorted([(sin(k), t) for t, ks in mapa["tecnologias"].items() for k in ks], key=lambda x: -len(x[0]))
        self.exacto = {sin(t): t for t in mapa["tecnologias"]}

    def __call__(self, nombre):
        s = sin(nombre)
        if s in ("fuel-gas", "fuel gas"):
            return "Fuel-gas"                     # UNEF y REE la separan de «Turbina vapor, gas y fuel»
        if s in self.exacto:
            return self.exacto[s]
        for k, t in self.kw:
            if s == k:
                return t
        for k, t in self.kw:
            if k in s and not s.startswith(("total", "saldo", "comercializ", "consumidor", "genericas", "unidades", "programa enlace")):
                return t
        return None


def _ajusta(p, n):
    """Lleva el vector de precios p a n periodos (media si hay más, repetición si hay menos)."""
    if p is None:
        return None
    p = np.asarray(p, float)
    m = len(p)
    if m == n:
        return p
    if m % n == 0:
        return np.nanmean(p.reshape(n, m // n), axis=1)
    if n % m == 0:
        return np.repeat(p, n // m)
    return None


def _media_filas(vs):
    n = max(len(v) for v in vs)
    m = np.full((len(vs), n), np.nan)
    for i, v in enumerate(vs):
        m[i, :len(v)] = v
    cuenta = (~np.isnan(m)).sum(axis=0)
    return np.where(cuenta > 0, np.nansum(m, axis=0) / np.maximum(cuenta, 1), np.nan)


def _ing(en, pr):
    if pr is not None and len(pr) != len(en):
        pr = _ajusta(pr, len(en))
    if pr is None:
        return None
    ok = ~np.isnan(en) & ~np.isnan(pr)
    return float(np.sum(en[ok] * pr[ok])) if ok.any() else None


def procesar(hojas, dia, precios=None):
    """hojas: dict nombre->filas (I3DIA01...). precios: dict opcional con vectores ESIOS
    {'spot','ida1','ida2','ida3','continuo'}. Devuelve (DataFrame, sin_clasificar)."""
    precios = precios or {}
    tec = Tec(cargar_mapa())
    filas, aviso = [], {}
    N = periodos_dia(hojas)
    _cache = {}

    def P(clave, n):
        """Precio ESIOS `clave` colocado en n periodos del día (por fecha y hora)."""
        if (clave, n) not in _cache:
            _cache[(clave, n)] = vector_precio(precios.get(clave), dia, n)
        return _cache[(clave, n)]

    def add(mercado, t, mag, valor, fase="", tip="", sent=""):
        filas.append({"fecha": dia, "mercado": mercado, "tecnologia": t, "magnitud": mag, "fase": fase, "tipologia": tip, "sentido": sent, "valor": float(valor)})

    def hoja(n):
        d = hojas.get(f"I3DIA{n:02d}")
        return leer(d, N) if d else []

    def energia(mercado, t, vec, **kw):
        add(mercado, t, "energia", np.nansum(vec), **kw)

    # ---- programas simples
    for n, nombre in ((1, "PDVP"), (2, "P48"), (18, "PHF")):
        for lab, v in hoja(n):
            t = tec(lab.get("Concepto", ""))
            if t:
                energia(nombre, t, v)
    # ---- PDBF: mercado diario y bilaterales
    for lab, v in hoja(14):
        t = tec(lab.get("Concepto", ""))
        if not t:
            continue
        tr = sin(lab.get("Tipo Transacción", ""))
        energia("PBF", t, v)
        if tr.startswith("bilat"):
            energia("Bilaterales", t, v)
        else:
            energia("Diario", t, v)
            i = _ing(v, P("spot", len(v)))
            if i is not None:
                add("Diario", t, "ingreso", i)
    # ---- intradiarios (diferencias entre programas, solo periodos que cubre cada sesión) y continuo
    base = {}
    for lab, v in hoja(1):
        t = tec(lab.get("Concepto", ""))
        if t:
            base[t] = v.copy()
    sesiones = {}
    for lab, v in hoja(13):
        m = re.match(r"PHF-?(\d+)", lab.get("Programa", ""))
        t = tec(lab.get("Concepto", ""))
        if m and t:
            sesiones.setdefault(int(m.group(1)), {})[t] = v
    actual = {t: v.copy() for t, v in base.items()}
    ks = sorted(sesiones)
    for k in ks:
        ida = min(k, 3)                           # PHF-k = programa tras la sesión intradiaria k
        nombre = f"Intradiario {ida}"
        for t, v in sesiones[k].items():
            ant = actual.get(t, np.zeros_like(v))
            n = min(len(ant), len(v))
            nuevo = ant[:n].copy()
            cub = ~np.isnan(v[:n])
            d = np.where(cub, np.nan_to_num(v[:n]) - np.nan_to_num(ant[:n]), 0.0)
            nuevo[cub] = v[:n][cub]
            actual[t] = nuevo
            if np.abs(d).sum() > 0:
                sg = "Subir" if d.sum() > 0 else "Bajar"
                add(nombre, t, "energia", d.sum(), sent=sg)
                i = _ing(d, P(f"ida{ida}", len(d)))
                if i is not None:
                    add(nombre, t, "ingreso", i, sent=sg)
    for lab, v in hoja(18):
        t = tec(lab.get("Concepto", ""))
        if not t:
            continue
        ant = actual.get(t, np.zeros_like(v))
        n = min(len(ant), len(v))
        d = np.nan_to_num(v[:n]) - np.nan_to_num(ant[:n])
        if np.abs(d).sum() > 0:
            sg = "Subir" if d.sum() > 0 else "Bajar"
            add("Continuo", t, "energia", d.sum(), sent=sg)
            i = _ing(d, P("continuo", len(d)))
            if i is not None:
                add("Continuo", t, "ingreso", i, sent=sg)

    # ---- precios por (redespacho, sentido, concepto)
    def tabla_precios(n):
        p = {}
        for lab, v in hoja(n):
            p[(lab.get("Redespacho", ""), lab.get("Sentido", ""), tec(lab.get("Concepto", "")))] = v
        return p

    p_md, p_tr = tabla_precios(9), tabla_precios(10)

    # ---- restricciones del mercado diario (fase I y II)
    for lab, v in hoja(3):
        t = tec(lab.get("Concepto", ""))
        if not t:
            continue
        red, sent = lab.get("Redespacho", ""), lab.get("Sentido", "")
        fase = FASE2 if red.upper().startswith("ECO") else FASE1
        tip = lab.get("Tipo Restricción", "")
        tip = "" if tip.upper() in ("N/A", "NA") else tip
        energia("Restricciones MD", t, v, fase=fase, tip=tip, sent=sent)
        pr = p_md.get((red, sent, t))
        if pr is not None:
            i = _ing(v, pr)
            if i is not None:
                add("Restricciones MD", t, "ingreso", i, fase, tip, sent)
        if fase == FASE1 and sent == "Subir" and tip in ("COT", "SOT") and P("spot", len(v)) is not None:
            x = _ing(v, P("spot", len(v)))
            if x is not None:
                add("Restricciones MD", t, "energia_x_spot", x, fase, tip, sent)
    # ---- restricciones de tiempo real y otros ajustes
    for lab, v in hoja(8):
        t = tec(lab.get("Concepto", ""))
        if not t:
            continue
        red, sent = lab.get("Redespacho", ""), lab.get("Sentido", "")
        tip = lab.get("Tipo Restricción", "")
        tip = "" if tip.upper() in ("N/A", "NA") else tip
        if red.upper() in ("UPOTROR", "UPLTROR"):
            energia("Restricciones TR", t, v, fase=TRF, tip=tip, sent=sent)
            i = _ing(v, p_tr.get((red, sent, t)))
            if i is not None:
                add("Restricciones TR", t, "ingreso", i, TRF, tip, sent)
        else:
            energia("Otros", t, v, fase="", tip=red, sent=sent)
    # ---- terciaria
    pt = {}
    for lab, v in hoja(16):
        pt.setdefault((lab.get("Redespacho", ""), lab.get("Sentido", "")), []).append(v)
    pt = {k: (_media_filas(v) if len(v) > 1 else v[0]) for k, v in pt.items()}
    for lab, v in hoja(7):
        t = tec(lab.get("Concepto", ""))
        if not t:
            continue
        red, sent = lab.get("Redespacho", ""), lab.get("Sentido", "")
        energia("Terciaria", t, v, tip=red, sent=sent)
        pr = pt.get((red, "No aplica")) if red == "TERPRO" else pt.get((red, sent))
        if pr is not None:
            i = _ing(v, pr)
            if i is not None:
                add("Terciaria", t, "ingreso", i, "", red, sent)
    cols = ["fecha", "mercado", "tecnologia", "magnitud", "fase", "tipologia", "sentido", "valor"]
    df = pd.DataFrame(filas, columns=cols)
    if len(df):
        df = df.groupby(["fecha", "mercado", "tecnologia", "magnitud", "fase", "tipologia", "sentido"], as_index=False)["valor"].sum()
    return df, aviso


def info_sesiones(hojas):
    """Diagnóstico: periodos cubiertos y energía movida por cada PHF-k de la hoja 13."""
    res = []
    prev = None
    ses = {}
    for lab, v in leer(hojas.get("I3DIA13", [])):
        m = re.match(r"PHF-?(\d+)", lab.get("Programa", ""))
        if m:
            ses.setdefault(int(m.group(1)), []).append((lab.get("Concepto", ""), v))
    for k in sorted(ses):
        cub = max(int(np.sum(~np.isnan(v))) for _, v in ses[k])
        tot = sum(float(np.nansum(v)) for c, v in ses[k] if tec_nombre(c))
        res.append(f"PHF-{k}: periodos cubiertos {cub}, suma generación {tot:.0f}")
    return "\n".join(res)


def tec_nombre(c):
    return Tec(cargar_mapa())(c)


def cierre_por_tecnologia(df):
    """Diagnóstico: por tecnología, cómo cierra la cascada contra el P48 (MWh)."""
    e = df[df["magnitud"] == "energia"]
    g = e.groupby(["tecnologia", "mercado"])["valor"].sum().unstack("mercado").fillna(0)
    for c in ("PBF", "Restricciones MD", "Intradiario 1", "Intradiario 2", "Intradiario 3", "Continuo", "Restricciones TR", "Otros", "Terciaria", "P48", "PDVP", "PHF"):
        if c not in g:
            g[c] = 0.0
    g["calc"] = g["PBF"] + g["Restricciones MD"] + g["Intradiario 1"] + g["Intradiario 2"] + g["Intradiario 3"] + g["Continuo"] + g["Restricciones TR"] + g["Otros"] + g["Terciaria"]
    g["dif"] = g["calc"] - g["P48"]
    g["dif_pdvp"] = g["PBF"] + g["Restricciones MD"] - g["PDVP"]
    g["dif_phf"] = g["PDVP"] + g["Intradiario 1"] + g["Intradiario 2"] + g["Intradiario 3"] + g["Continuo"] - g["PHF"]
    return g[["PBF", "Restricciones MD", "PDVP", "dif_pdvp", "PHF", "dif_phf", "Restricciones TR", "Otros", "Terciaria", "P48", "calc", "dif"]].round(0)
