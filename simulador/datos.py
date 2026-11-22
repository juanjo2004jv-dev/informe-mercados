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
    df.to_csv(ALMACEN / f"{a}-{m:02d}.csv.gz", float_format="%.4f")
    return cob


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
                av.append(f"Precio de banda aFRR a {d}ir estimado en {n} cuartos (coste ÷ banda requerida).")
    # Precio de referencia del continuo ausente: se usa el del diario (aviso).
    if df["cont"].isna().any():
        n = int(df["cont"].isna().sum())
        df["cont"] = df["cont"].fillna(df["da"])
        av.append(f"Continuo sin precio en {n} cuartos: se usa el diario.")
    for c in ("act_sub", "act_baj", "m_sub", "m_baj", "rt2_e_sub", "rt2_e_baj"):
        if c in df:
            df[c] = df[c].fillna(0.0)
    faltan = [c for c in ("da", "bp_sub", "bp_baj", "pe_sub", "pe_baj", "banda_sub", "banda_baj")
              if df[c].isna().mean() > 0.0]
    for c in faltan:
        av.append(f"{c}: {df[c].isna().mean():.2%} de cuartos sin dato; se rellenan con el último valor.")
        df[c] = df[c].ffill().bfill()
    return df, av


def perfil_fv(df, fv_mwp, ratio_dc_ac=1.0):
    """Perfil FV (MW AC) a partir de la FV peninsular real de ESIOS (1295), normalizada por su máximo
    móvil de 30 días. SUPUESTO: el perfil nacional representa la forma diaria de una planta en el sur
    (más ancho que un emplazamiento real). Se sustituirá por PVGIS o una curva propia."""
    if not fv_mwp:
        return pd.Series(0.0, index=df.index)
    s = df["fv_nac"].clip(lower=0).fillna(0)
    ref = s.rolling("30D", center=True, min_periods=96).max().replace(0, np.nan).bfill().ffill()
    pu = (s / ref).clip(0, 1).fillna(0)
    return (pu * fv_mwp).clip(upper=fv_mwp / ratio_dc_ac)
