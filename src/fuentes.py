"""Fuentes públicas complementarias, gratuitas y sin clave (todo determinista, sin IA):
  · REE en tiempo real (demanda.ree.es): rellena los huecos del tiempo real de ESIOS.
  · REData (apidatos.ree.es): balance diario oficial, para contrastar el tiempo real.
  · OMIE (www.omie.es/es/file-download): precios marginales del diario e IDA1-3, para contrastar ESIOS.
Si una fuente no responde, se devuelve vacío y el informe sale igual (lo dice el control de calidad)."""
import json
import time

import numpy as np
import pandas as pd
import requests

from . import analisis as A

TZ = A.TZ
CAB = {"User-Agent": "informe-mercados/1.0 (GitHub Actions; informe semanal sin animo de lucro)"}

URL_TR = ("https://demanda.ree.es/WSvisionaMovilesPeninsulaRest/resources/demandaGeneracionPeninsula"
          "?callback=cb&curva=DEMANDAAU&fecha={}")
URL_RD = ("https://apidatos.ree.es/es/datos/{ruta}?start_date={a}T00:00&end_date={b}T23:59&time_trunc=day"
          "&geo_trunc=electric_system&geo_limit=peninsular&geo_ids=8741")
URL_OMIE = "https://www.omie.es/es/file-download?parents%5B0%5D={p}&filename={p}_{f}.1"

# serie del informe -> campo de demanda.ree.es. Antes de usarse para rellenar, cada pareja se valida
# contra ESIOS en los cuartos de hora con dato en las dos fuentes (ver rellenar_tiempo_real).
MAPA_TR = {
    "demanda_real": ("dem", 1293), "gen_solar_fv": ("solFot", 1295), "gen_eolica": ("eol", 551),
    "mix_hidraulica": ("hid", 546), "mix_eolica": ("eol", 551), "mix_solar_fv": ("solFot", 1295),
    "mix_solar_ter": ("solTer", 1294), "mix_term_ren": ("bio", 1296), "mix_nuclear": ("nuc", 549),
    "mix_ciclo": ("cc", 550), "mix_carbon": ("car", 547), "mix_fuel_gas": ("gf", 548),
    "mix_cogen": ("cogenResto", 1297), "mix_vapor": ("vap", 2344),
    "bal_turb_bombeo": ("turb", 2079), "bal_cons_bombeo": ("conb", 2078), "bal_intercambios": ("inter", 553),
    "bal_enlace_balear": ("icb", 554), "bal_bat_carga": ("consBat", 2166), "bal_bat_entrega": ("bat", 2167),
}


def _get(url, intentos=3, timeout=60):
    ultimo = None
    for i in range(intentos):
        try:
            r = requests.get(url, headers=CAB, timeout=timeout)
            if r.status_code == 200:
                return r.text
            ultimo = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            ultimo = str(e)[:80]
        time.sleep(2 * 2 ** i)
    raise RuntimeError(f"{url.split('?')[0]}: {ultimo}")


# ------------------------------------------------------------------ REE en tiempo real
def ree_tr_dia(fecha):
    """DataFrame de 5 minutos (índice UTC) de un día. El servicio devuelve también horas del día
    anterior y del siguiente: se filtra por fecha y se quitan los ts duplicados."""
    txt = _get(URL_TR.format(fecha)).strip()
    if txt.startswith("cb("):
        txt = txt[3:]
    txt = txt.rstrip().rstrip(";").rstrip(")")
    df = pd.DataFrame(json.loads(txt).get("valoresHorariosGeneracion", []))
    if df.empty:
        return df
    df = df[df["ts"].astype(str).str.startswith(str(fecha))]
    t = pd.to_datetime(df["ts"], format="%Y-%m-%d %H:%M", errors="coerce")
    df = df[t.notna()].assign(_t=t[t.notna()])
    try:   # día de cambio de hora (25 h): la hora repetida viene dos veces y en orden
        idx = pd.DatetimeIndex(df["_t"]).tz_localize(TZ, ambiguous="infer", nonexistent="shift_forward")
    except Exception:
        df = df.drop_duplicates("ts")
        idx = pd.DatetimeIndex(df["_t"]).tz_localize(TZ, ambiguous="NaT", nonexistent="NaT")
    df.index = idx.tz_convert("UTC")
    df = df[df.index.notna()]
    df = df[~df.index.duplicated(keep="first")]
    return df.drop(columns=["ts", "_t"]).apply(pd.to_numeric, errors="coerce").sort_index()


def ree_tr_semana(ini, fin):
    """Media de cada cuarto de hora [ini, fin) de todos los campos de demanda.ree.es."""
    trozos = []
    for d in pd.date_range(ini.tz_convert(TZ).date(), (fin - pd.Timedelta(minutes=1)).tz_convert(TZ).date()):
        trozos.append(ree_tr_dia(d.date().isoformat()))
    df = pd.concat([x for x in trozos if len(x)]) if any(len(x) for x in trozos) else pd.DataFrame()
    if df.empty:
        return df
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = df[(df.index >= ini.tz_convert("UTC")) & (df.index < fin.tz_convert("UTC"))]
    return df.resample("15min").mean()


def rellenar_tiempo_real(datos, meta, ini, fin, tol_uso=0.05):
    """Completa con REE en tiempo real los cuartos de hora en que ESIOS no tiene dato.
    Una serie solo se rellena si, en los cuartos comunes, la diferencia media con ESIOS es <= tol_uso
    (5 %) de su nivel medio. Devuelve info para el control de calidad y anota el origen de cada serie."""
    info = {"ok": False, "validacion": [], "error": None}
    try:
        tr = ree_tr_semana(ini, fin)
    except Exception as e:
        info["error"] = str(e)[:120]
        return info
    if tr.empty:
        info["error"] = "sin datos"
        return info
    info["ok"] = True
    rej = A.rejilla(ini, fin)
    for k, (campo, ind) in MAPA_TR.items():
        if campo not in tr.columns:
            continue
        r = tr[campo].reindex(rej)
        s = datos.get(k)
        e = A.alinear(s, rej) if s is not None and len(s) else pd.Series(np.nan, index=rej)
        comun = e.notna() & r.notna()
        rel, dif = np.nan, np.nan
        if comun.sum() >= 50:
            dif = float((e[comun] - r[comun]).abs().mean())
            base = float(e[comun].abs().mean())
            rel = (dif / base) if base >= 1 else (0.0 if dif < 1 else np.inf)
        usar = bool(rel == rel and rel <= tol_uso)
        hueco = e.isna() & r.notna()
        if usar and hueco.any():
            nueva = r[hueco]
            datos[k] = nueva if s is None or not len(s) else s.combine_first(nueva).sort_index()
        m = meta.setdefault(k, {"nombre": k.split("_", 1)[1].replace("_", " ") if k.startswith(("mix_", "bal_")) else k, "id": ind, "api": "—"})
        m["origen"] = {"esios": float(e.notna().mean()), "ree": float((hueco & usar).mean()),
                       "sin": float((e.isna() & ~(hueco & usar)).mean())}
        info["validacion"].append({"clave": k, "campo": campo, "id": ind, "n": int(comun.sum()), "dif_mw": dif, "rel": rel,
                                   "usada": usar, "rellenado_pct": float((hueco & usar).mean() * 100)})
    return info


# ------------------------------------------------------------------ REData (balance diario oficial)
def _redata(ruta, a, b):
    return json.loads(_get(URL_RD.format(ruta=ruta, a=a, b=b)))


def redata_semana(lunes):
    """Energías de la semana (GWh) según REData: generación por tecnología, demanda en barras de
    central, saldo de intercambios y bombeo. Vacío si no responde."""
    a, b = lunes.isoformat(), (lunes + pd.Timedelta(days=6)).isoformat()
    out = {"gen": {}, "balance": {}, "error": None}
    try:
        j = _redata("generacion/estructura-generacion", a, b)
        for x in j.get("included", []):
            at = x.get("attributes", {})
            out["gen"][at.get("title", x.get("id"))] = sum(v.get("value", 0) for v in at.get("values", [])) / 1000
        j = _redata("balance/balance-electrico", a, b)
        for x in j.get("included", []):
            for c in x.get("attributes", {}).get("content", []):
                at = c.get("attributes", {})
                out["balance"][c.get("type", at.get("title"))] = sum(v.get("value", 0) for v in at.get("values", [])) / 1000
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


# ------------------------------------------------------------------ OMIE
def omie_dia(fichero, fecha):
    """Precio marginal de España (columna 6; la 5 es Portugal) de un fichero de OMIE, índice UTC.
    fichero: 'marginalpdbc' o 'marginalpibc' con sufijo de sesión (p. ej. ('marginalpibc', '01')).
    Los ficheros cuartohorarios tienen 96 periodos (92/100 en los días de cambio de hora)."""
    p, ses = (fichero, "") if isinstance(fichero, str) else fichero
    txt = _get(URL_OMIE.format(p=p, f=pd.Timestamp(fecha).strftime("%Y%m%d") + ses))
    filas = []
    for lin in txt.splitlines():
        c = lin.strip().split(";")
        if len(c) >= 6 and c[0].isdigit() and c[3].isdigit():
            try:
                filas.append((int(c[3]), float(c[5].replace(",", "."))))
            except ValueError:
                continue
    if not filas:
        return pd.Series(dtype=float)
    ini = pd.Timestamp(fecha).tz_localize(TZ).tz_convert("UTC")
    paso = 60 if max(pr for pr, _ in filas) <= 25 else 15      # antes del 1-oct-2025 el diario era horario
    s = pd.Series({ini + pd.Timedelta(minutes=paso * (pr - 1)): v for pr, v in filas}).sort_index()
    return s


def omie_semana(lunes):
    """{'spot': Serie, 'ida1': …, 'ida2': …, 'ida3': …} de OMIE para la semana; error si no responde."""
    out, err = {}, None
    for k, f in (("spot", "marginalpdbc"), ("ida1", ("marginalpibc", "01")), ("ida2", ("marginalpibc", "02")), ("ida3", ("marginalpibc", "03"))):
        trozos = []
        for d in range(7):
            try:
                trozos.append(omie_dia(f, lunes + pd.Timedelta(days=d)))
            except Exception as e:
                err = str(e)[:120]
        trozos = [t for t in trozos if len(t)]
        if trozos:
            out[k] = pd.concat(trozos).sort_index()
    return out, err
