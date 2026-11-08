"""Histórico semanal de indicadores clave (data/historico_semanal.csv).

Cada informe actualiza la fila de su semana; `python -m src.historico --desde 2025-01-06`
reconstruye las semanas anteriores desde ESIOS con EXACTAMENTE el mismo cálculo (función kpis),
para que las series largas sean comparables. Sin IA: todo determinista.
"""
import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import analisis as A

RAIZ = Path(__file__).resolve().parent.parent
ARCH = RAIZ / "data" / "historico_semanal.csv"
COLS = ["etiqueta", "lunes", "precio_medio", "precio_min", "precio_max", "horas_neg", "spread_medio",
        "bess_1h", "bess_2h", "bess_4h", "captura_fv", "ratio_fv", "captura_eol", "ratio_eol",
        "gen_fv_gwh", "gen_eol_gwh", "demanda_gwh", "renovable_pct", "cobertura_spot"]


def kpis(lunes, spot, fv, eol, dem, bat):
    """spot/fv/eol/dem: series ya alineadas a la rejilla cuartohoraria de la semana."""
    r = {"lunes": lunes.isoformat()}
    iso = lunes.isocalendar()
    r["etiqueta"] = f"{iso.year}-S{iso.week:02d}"
    r["cobertura_spot"] = float(spot.notna().mean())
    r["precio_medio"] = float(spot.mean())
    r["precio_min"] = float(spot.min())
    r["precio_max"] = float(spot.max())
    r["horas_neg"] = float((spot <= 0).sum() / 4)
    dia = pd.Series(spot.index.tz_convert(A.TZ).date, index=spot.index)
    r["spread_medio"] = float(spot.groupby(dia).agg(lambda g: g.max() - g.min()).mean())
    for h in (1, 2, 4):
        b = A.bess_por_dia(spot, dict(bat, horas=h))
        v = [x[0] for x in b.values() if not np.isnan(x[0])]
        r[f"bess_{h}h"] = float(np.mean(v)) if v else np.nan
    for k, g in (("fv", fv), ("eol", eol)):
        if g is not None and g.notna().mean() > 0.5:
            c = A.captura(spot, g)
            r[f"captura_{k}"] = c
            r[f"ratio_{k}"] = c / r["precio_medio"] * 100 if r["precio_medio"] else np.nan
            r[f"gen_{k}_gwh"] = float(g.sum() / 4 / 1000)
    if dem is not None and dem.notna().mean() > 0.5:
        r["demanda_gwh"] = float(dem.sum() / 4 / 1000)
    return r


def cargar():
    if ARCH.exists():
        return pd.read_csv(ARCH)
    return pd.DataFrame(columns=COLS)


def actualizar(res, cfg, guardar=True):
    """Calcula la fila de la semana del informe, la inserta y devuelve el histórico completo."""
    s = res["series"]
    fila = kpis(res["lunes"], res["spot"], s.get("gen_solar_fv"), s.get("gen_eolica"), s.get("demanda_real"), cfg["bateria"])
    if res.get("mix"):
        fila["renovable_pct"] = res["mix"].get("renovable_pct")
    df = cargar()
    df = pd.concat([df[df["etiqueta"] != fila["etiqueta"]], pd.DataFrame([fila])], ignore_index=True)
    df = df.drop_duplicates("etiqueta", keep="last").sort_values("lunes").reset_index(drop=True)
    if guardar:
        _guardar(df)
    return df


def _guardar(df):
    ARCH.parent.mkdir(parents=True, exist_ok=True)
    df.drop_duplicates("etiqueta", keep="last").sort_values("lunes").reindex(columns=COLS).to_csv(ARCH, index=False, float_format="%.3f")


def _serie_tramos(cli, ind, ini, fin, geos=None, dias=31):
    """Descarga en tramos de `dias` (ESIOS limita el volumen por petición)."""
    partes, a = [], ini
    while a < fin:
        b = min(a + pd.Timedelta(days=dias), fin)
        try:
            _, s = cli.serie(ind, a, b, geos)
            if len(s):
                partes.append(s)
        except Exception as e:
            print(f"  aviso: {ind} {a.date()}–{b.date()}: {str(e)[:80]}")
        a = b
    if not partes:
        return pd.Series(dtype=float)
    s = pd.concat(partes)
    return s[~s.index.duplicated()].sort_index()


def reconstruir(desde, hasta, cfg):
    """Rellena el histórico desde ESIOS para las semanas [desde, hasta] que falten (lunes a lunes)."""
    from .esios import Esios

    cli = Esios()
    ids = {k: cfg["series"][k]["id"] for k in ("spot", "demanda_real")}
    for k in ("gen_solar_fv", "gen_eolica"):
        v = cfg.get("opcionales", {}).get(k, {})
        if v.get("id"):
            ids[k] = v["id"]
    df = cargar()
    hechas = set(df["etiqueta"]) if len(df) else set()
    lunes = desde - timedelta(days=desde.weekday())
    semanas = []
    while lunes <= hasta:
        iso = lunes.isocalendar()
        if f"{iso.year}-S{iso.week:02d}" not in hechas:
            semanas.append(lunes)
        lunes += timedelta(days=7)
    if not semanas:
        print("Histórico al día.")
        return df
    ini, _ = A.limites_semana(semanas[0])
    _, fin = A.limites_semana(semanas[-1])
    print(f"Descargando {len(semanas)} semanas ({semanas[0]} a {semanas[-1]})…")
    crudo = {k: _serie_tramos(cli, i, ini, fin, cfg["series"]["spot"].get("geo") if k == "spot" else None) for k, i in ids.items()}
    filas = []
    for lun in semanas:
        a, b = A.limites_semana(lun)
        idx = A.rejilla(a, b)
        al = {k: A.alinear(s, idx) for k, s in crudo.items()}
        if al["spot"].notna().mean() < 0.9:
            print(f"  {lun}: spot incompleto, se omite")
            continue
        filas.append(kpis(lun, al["spot"], al.get("gen_solar_fv"), al.get("gen_eolica"), al.get("demanda_real"), cfg["bateria"]))
    if filas:
        df = pd.concat([df, pd.DataFrame(filas)], ignore_index=True)
        _guardar(df)
    print(f"Histórico: {len(df)} semanas.")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2025-01-06")
    ap.add_argument("--hasta", default=None, help="lunes de la última semana (por defecto, la última completa)")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(RAIZ / "config.yml", encoding="utf-8"))
    hoy = date.today()
    ult = hoy - timedelta(days=hoy.weekday() + 7)
    reconstruir(date.fromisoformat(a.desde), date.fromisoformat(a.hasta) if a.hasta else ult, cfg)
