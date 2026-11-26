"""Datos del simulador: descarga de ESIOS a un almacén mensual propio y lectura a 15 minutos.

Independiente de src/ (el informe semanal): si uno cambia, el otro no se rompe.
Almacén: data/simulador/precios/AAAA-MM.csv.gz, índice UTC cada 15 min, una columna por serie.
"""
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
ALMACEN = RAIZ / "data" / "simulador" / "precios"
BASE = "https://api.esios.ree.es"
TZ = "Europe/Madrid"


def cargar_config():
    with open(Path(__file__).with_name("config.yml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


class Esios:
    """Cliente mínimo de solo lectura. El token solo se lee del entorno (secreto ESIOS_TOKEN)."""

    def __init__(self):
        token = os.environ.get("ESIOS_TOKEN")
        if not token:
            raise RuntimeError("Falta ESIOS_TOKEN (secreto del repositorio).")
        self.s = requests.Session()
        self.s.headers.update({
            "Accept": "application/json; application/vnd.esios-api-v1+json",
            "Content-Type": "application/json",
            "x-api-key": token,
        })

    def _get(self, ruta, params):
        err = None
        for i in range(5):
            try:
                r = self.s.get(BASE + ruta, params=params, timeout=120)
            except requests.RequestException as e:
                err = e
                time.sleep(3 * 2 ** i)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                err = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(3 * 2 ** i)
                continue
            r.raise_for_status()
        raise RuntimeError(f"ESIOS no responde ({ruta}): {err}")

    def serie(self, ind, ini, fin):
        """Serie cruda a 15 min (UTC). Energías por periodo -> MW medios; 5 min -> media del cuarto;
        horaria -> se repite en los 4 cuartos. Zona: España (3) o Península (8741). `fin` exclusivo."""
        j = self._get(f"/indicators/{ind}", {"start_date": ini.isoformat(), "end_date": fin.isoformat()})
        meta = j["indicator"]
        df = pd.DataFrame(meta.get("values", []))
        if df.empty:
            return pd.Series(dtype=float)
        if "geo_id" in df.columns and df["geo_id"].nunique() > 1:
            geo = next((g for g in (3, 8741) if (df["geo_id"] == g).any()), df["geo_id"].value_counts().idxmax())
            df = df[df["geo_id"] == geo]
        t = pd.to_datetime(df["datetime_utc"], utc=True)
        s = pd.Series(df["value"].astype(float).values, index=t).groupby(level=0).mean().sort_index()
        s = s[(s.index >= ini.tz_convert("UTC")) & (s.index < fin.tz_convert("UTC"))]
        if s.empty:
            return s
        paso = s.index.to_series().diff().dropna().median() / pd.Timedelta(hours=1) if len(s) > 1 else 0.25
        magn = " ".join(m.get("name", "") for m in meta.get("magnitud", []) or []).lower()
        if "energ" in magn:
            s = s / paso
        idx = pd.date_range(ini.tz_convert("UTC"), fin.tz_convert("UTC"), freq="15min", inclusive="left")
        if paso < 0.25 - 1e-9:
            s = s.resample("15min").mean()
        return s.reindex(idx, method="ffill", limit=int(max(paso / 0.25 - 1, 0))) if paso > 0.25 + 1e-9 else s.reindex(idx)


def _mes(a, m):
    ini = pd.Timestamp(year=a, month=m, day=1, tz=TZ)
    return ini, ini + pd.offsets.MonthBegin(1)


def descargar_mes(a, m, cli=None, cfg=None):
    """Descarga todas las series de un mes y las guarda en el almacén. Devuelve la cobertura por serie."""
    cfg = cfg or cargar_config()
    cli = cli or Esios()
    ini, fin = _mes(a, m)
    cols, cob = {}, {}
    for clave, sd in cfg["series"].items():
        s = pd.Series(dtype=float)
        for ind in [sd["id"], sd.get("respaldo")]:
            if not ind:
                continue
            try:
                s2 = cli.serie(ind, ini, fin)
            except Exception as e:  # noqa: BLE001 - se registra y se sigue
                print(f"  {clave} ({ind}): error {e}")
                s2 = pd.Series(dtype=float)
            if s2.empty or s2.notna().mean() < 0.05:
                # Reintento por semanas: un mes entero a veces vuelve vacío (respuesta truncada o
                # error transitorio de la API) y por tramos sí llega. Solo ante un mes casi vacío:
                # varias series son dispersas por naturaleza (RRTT, mFRR, IDA3) y no deben reintentarse.
                s2 = s2.combine_first(_por_tramos(cli, ind, ini, fin)) if not s2.empty else _por_tramos(cli, ind, ini, fin)
            if s2.empty:
                continue
            s = s2 if s.empty else s.combine_first(s2)
            if not s.empty and s.notna().mean() > 0.999:
                break
        cols[clave] = s
        cob[clave] = float(s.notna().mean()) if len(s) else 0.0
        print(f"  {a}-{m:02d} {clave:10s} id {sd['id']:>6}: cobertura {cob[clave]:.1%}")
    idx = pd.date_range(ini.tz_convert("UTC"), fin.tz_convert("UTC"), freq="15min", inclusive="left")
    df = pd.DataFrame({k: v.reindex(idx) if len(v) else np.nan for k, v in cols.items()}, index=idx)
    df.index.name = "utc"
    ALMACEN.mkdir(parents=True, exist_ok=True)
    f = ALMACEN / f"{a}-{m:02d}.csv.gz"
    if f.exists():
        # Nunca se empeora lo almacenado: lo nuevo manda y lo que falte se completa con lo anterior.
        prev = pd.read_csv(f, index_col=0, parse_dates=True)
        prev.index = pd.to_datetime(prev.index, utc=True)
        prev = prev.reindex(idx)
        for c in df.columns:
            if c in prev:
                antes = prev[c].notna().mean()
                df[c] = df[c].combine_first(prev[c])
                if df[c].notna().mean() > cob[c] + 1e-9:
                    print(f"  {c:10s}: se conserva lo almacenado donde la descarga nueva no trae dato "
                          f"({cob[c]:.1%} -> {df[c].notna().mean():.1%}; antes {antes:.1%})")
                cob[c] = float(df[c].notna().mean())
    df.to_csv(f, float_format="%.4f")
    return cob


def _por_tramos(cli, ind, ini, fin, dias=7):
    partes, t = [], ini
    while t < fin:
        t2 = min(t + pd.Timedelta(days=dias), fin)
        try:
            p = cli.serie(ind, t, t2)
            if not p.empty:
                partes.append(p)
        except Exception as e:  # noqa: BLE001
            print(f"    tramo {t.date()} ({ind}): error {e}")
        t = t2
    if not partes:
        return pd.Series(dtype=float)
    s = pd.concat(partes)
    return s[~s.index.duplicated(keep="first")].sort_index()


def leer(ini, fin):
    """Datos a 15 min entre dos fechas locales (fin exclusivo), desde el almacén."""
    ini, fin = pd.Timestamp(ini, tz=TZ), pd.Timestamp(fin, tz=TZ)
    partes = []
    for p in pd.period_range(ini.tz_localize(None), (fin - pd.Timedelta(minutes=15)).tz_localize(None), freq="M"):
        f = ALMACEN / f"{p.year}-{p.month:02d}.csv.gz"
        if not f.exists():
            raise FileNotFoundError(f"Falta {f.name}: lanzar la descarga de ese mes.")
        partes.append(pd.read_csv(f, index_col=0, parse_dates=True))
    df = pd.concat(partes)
    df.index = pd.to_datetime(df.index, utc=True)
    return df[(df.index >= ini.tz_convert("UTC")) & (df.index < fin.tz_convert("UTC"))]


def completar(df, cfg):
    """Rellena huecos con reglas documentadas y devuelve (df, avisos)."""
    av = []
    df = df.copy()
    # Coherencia del precio de banda publicado con coste ÷ banda requerida. Detectado el 22-04-2025:
    # el indicador de respaldo devolvió el coste (€/h) en lugar del precio (€/MW·h), 1000 veces mayor.
    for d, coste, req in (("sub", "coste_sub", "req_sub"), ("baj", "coste_baj", "req_baj")):
        col = f"bp_{d}"
        if coste in df and req in df:
            est = df[coste] / df[req].where(df[req] > 0)
            rel = (df[col] - est).abs() / est.clip(lower=1.0)
            malo = (rel > 0.5) & (df[col] > 20) & est.notna()
            if malo.any():
                df.loc[malo, col] = est[malo]
                av.append(f"Precio de banda aFRR a {'subir' if d == 'sub' else 'bajar'} incoherente con coste ÷ banda requerida en "
                          f"{int(malo.sum())} cuartos: se sustituye por la estimación.")
    # Banda aFRR sin precio publicado: precio = coste / banda requerida (método del informe semanal,
    # validado con error medio < 1 %). Coste en €/h -> €/MW·h.
    for d, coste, req in (("sub", "coste_sub", "req_sub"), ("baj", "coste_baj", "req_baj")):
        col = f"bp_{d}"
        hueco = df[col].isna()
        if hueco.any() and coste in df and req in df:
            est = df[coste] / df[req].where(df[req] > 0)
            df.loc[hueco, col] = est[hueco]
            n = int((hueco & df[col].notna()).sum())
            if n:
                av.append(f"Precio de banda aFRR a {'subir' if d == 'sub' else 'bajar'} estimado en {n} cuartos (coste ÷ banda requerida).")
    # Precio de referencia del continuo ausente: se usa el del diario (aviso).
    if df["cont"].isna().any():
        n = int(df["cont"].isna().sum())
        df["cont"] = df["cont"].fillna(df["da"])
        av.append(f"Continuo sin precio en {n} cuartos: se usa el diario.")
    for c in ("act_sub", "act_baj", "m_sub", "m_baj", "rt2_e_sub", "rt2_e_baj"):
        if c in df:
            df[c] = df[c].fillna(0.0)
    # Días sin precio del diario (más de 4 cuartos vacíos): no se simulan. Rellenar un mes entero con
    # el último valor fabricaría ingresos; mejor excluir el día y avisar.
    dia = df.index.tz_convert(TZ).normalize()
    vacios = df["da"].isna().groupby(dia).transform("sum")
    excl = vacios > 4
    if excl.any():
        n = int(pd.Series(dia[excl]).nunique())
        df = df[~excl]
        av.append(f"{n} días excluidos por falta de precio del mercado diario.")
    faltan = [c for c in ("da", "bp_sub", "bp_baj", "pe_sub", "pe_baj", "banda_sub", "banda_baj")
              if df[c].isna().mean() > 0.0]
    for c in faltan:
        av.append(f"{c}: {df[c].isna().mean():.2%} de cuartos sin dato; se rellenan con el último valor.")
        df[c] = df[c].ffill().bfill()
    return df, av


PVGIS = RAIZ / "data" / "simulador" / "pvgis"


def pvgis_mensual(lat, lon, seguidor=True, perdidas=14.0):
    """Producción mensual media (kWh/kWp) de un emplazamiento según PVGIS 5.3 (JRC, base SARAH3).
    seguidor=True: seguidor de un eje horizontal norte-sur (eje inclinado 0°); False: fijo con ángulos óptimos.
    Se guarda en data/simulador/pvgis/ para no repetir la consulta (y para poder simular sin red)."""
    import json
    tipo = "seguidor" if seguidor else "fijo"
    f = PVGIS / f"{lat:.3f}_{lon:.3f}_{tipo}_{perdidas:g}.json"
    if not f.exists():
        par = {"lat": lat, "lon": lon, "peakpower": 1, "loss": perdidas, "outputformat": "json",
               "raddatabase": "PVGIS-SARAH3"}
        par.update({"inclined_axis": 1, "inclinedaxisangle": 0} if seguidor else {"optimalangles": 1})
        r = requests.get("https://re.jrc.ec.europa.eu/api/v5_3/PVcalc", params=par, timeout=60)
        r.raise_for_status()
        PVGIS.mkdir(parents=True, exist_ok=True)
        f.write_text(r.text, encoding="utf-8")
    j = json.loads(f.read_text(encoding="utf-8"))
    mens = j["outputs"]["monthly"]
    # Con inclined_axis PVGIS devuelve también un bloque "fixed" (horizontal): hay que coger el del montaje pedido.
    if isinstance(mens, dict):
        filas = mens["inclined_axis"] if seguidor else mens["fixed"]
    else:
        filas = mens
    return {int(x["month"]): float(x["E_m"]) for x in filas}


def perfil_fv(df, fv_mwp, ratio_dc_ac=1.0, emplazamiento=None):
    """Perfil FV (MW AC).
    - Sin emplazamiento: FV peninsular real de ESIOS (1295) normalizada por su máximo móvil de 30 días
      (SUPUESTO: la forma nacional representa una planta del sur).
    - Con emplazamiento {lat, lon, seguidor, perdidas}: la forma cuarto a cuarto y la variabilidad diaria son
      las de la FV peninsular real (que es la que mueve los precios), y la energía de cada mes es la de PVGIS
      para ese emplazamiento (kWh/kWp del mes medio, proporcional a los días simulados)."""
    if not fv_mwp:
        return pd.Series(0.0, index=df.index)
    s = df["fv_nac"].clip(lower=0).fillna(0)
    techo = fv_mwp / ratio_dc_ac
    if not emplazamiento:
        ref = s.rolling("30D", center=True, min_periods=96).max().replace(0, np.nan).bfill().ffill()
        pu = (s / ref).clip(0, 1).fillna(0)
        return (pu * fv_mwp).clip(upper=techo)
    em = pvgis_mensual(emplazamiento["lat"], emplazamiento["lon"], emplazamiento.get("seguidor", True),
                       emplazamiento.get("perdidas", 14.0))
    loc = s.index.tz_convert("Europe/Madrid")
    clave = loc.year * 100 + loc.month
    out = pd.Series(0.0, index=s.index)
    for k in np.unique(clave):
        mk = clave == k
        anio, mes = divmod(int(k), 100)
        dias_mes = pd.Period(year=anio, month=mes, freq="M").days_in_month
        dias = len(np.unique(loc[mk].normalize()))
        objetivo = em[mes] * fv_mwp * dias / dias_mes     # kWh/kWp = MWh/MWp -> MWh en esos días
        sk = s[mk]
        if float(sk.sum()) <= 0:
            continue
        f = objetivo / float(sk.sum() * 0.25)
        for _ in range(20):   # reescala tras recortar al techo AC para conservar la energía de PVGIS
            v = (sk * f).clip(upper=techo)
            e = float(v.sum() * 0.25)
            if e <= 0 or abs(e - objetivo) < 1e-6 * objetivo:
                break
            f *= objetivo / e
        out[mk] = v
    return out.clip(upper=techo)


def tramos(carpeta, sufijo="_mensual_eur_mw.csv"):
    """Ficheros de resultados de un escenario ordenados para combinarlos con keep="last": primero por fecha
    de generación (guardada en *_avisos.json; los antiguos sin fecha van primero) y, a igualdad, por longitud
    del tramo. Así gana siempre la simulación más reciente y, entre las antiguas, la más larga."""
    import json
    out = []
    for f in Path(carpeta).glob(f"*{sufijo}"):
        tramo = f.name[: -len(sufijo)]
        gen = ""
        av = f.with_name(f"{tramo}_avisos.json")
        if av.exists():
            try:
                gen = json.load(open(av, encoding="utf-8")).get("generado", "")
            except ValueError:
                gen = ""
        try:
            a, b = tramo.split("_")
            dias = (pd.Timestamp(b) - pd.Timestamp(a)).days
        except ValueError:
            dias = 0
        out.append((gen, dias, tramo, f))
    return [x[-1] for x in sorted(out)]

