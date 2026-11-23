"""Previsiones deterministas para decidir sin conocer el futuro (modo de previsión imperfecta).

Solo usan información publicada ANTES de la hora de decisión:
- Diario de D: se oferta antes de las 12:00 de D-1. El último precio del diario conocido es el de D-1
  (publicado hacia las 13:00 de D-2), así que la historia útil son los días D-1, D-2, …
- Banda aFRR de D: se oferta antes de las 16:00 de D-1; el último precio conocido es el de D-1.
Método por defecto: media, cuarto a cuarto (misma hora local), de los últimos 7 días (elegido con 2025 y
comprobado fuera de muestra en 2026: captura del arbitraje en el diario 92,9 % y 95,7 %). Es el tipo de
previsión «climatológica» que en la literatura recupera la mayor parte del valor del arbitraje sin
modelos de aprendizaje (y es reproducible, sin IA en ejecución).
"""
import numpy as np
import pandas as pd

TZ = "Europe/Madrid"


def _matriz(s):
    """Serie a 15 min (UTC) -> tabla día local × minuto del día local."""
    loc = s.index.tz_convert(TZ)
    t = pd.DataFrame({"v": s.values, "dia": loc.normalize().tz_localize(None), "min": loc.hour * 60 + loc.minute})
    return t.pivot_table(index="dia", columns="min", values="v", aggfunc="mean")


def prevision(s, dias=7, metodo="mediana"):
    """Previsión de la serie para cada cuarto con los N días anteriores (sin usar el propio día)."""
    m = _matriz(s)
    hist = m.shift(1)
    if metodo == "mediana":
        p = hist.rolling(dias, min_periods=1).median()
    elif metodo == "media":
        p = hist.rolling(dias, min_periods=1).mean()
    elif metodo == "mismo_dia_semana":     # mismo día de la semana de las N semanas anteriores
        p = pd.concat([m.shift(7 * k) for k in range(1, dias + 1)]).groupby(level=0).median().reindex(m.index)
    else:
        raise ValueError(metodo)
    p = p.ffill(axis=1).bfill(axis=1)       # minutos sin historia (cambio de hora) -> vecinos
    loc = s.index.tz_convert(TZ)
    filas = loc.normalize().tz_localize(None)
    cols = loc.hour * 60 + loc.minute
    vals = np.array([p.at[f, c] if (f in p.index and c in p.columns) else np.nan for f, c in zip(filas, cols)])
    return pd.Series(vals, index=s.index)


def anadir(df, cfg):
    """Añade las columnas *_prev que usa el motor en modo de previsión imperfecta."""
    pr = cfg.get("prevision", {})
    n, met = pr.get("dias", 7), pr.get("metodo", "media")
    d = df.copy()
    for c in ("da", "bp_sub", "bp_baj"):
        d[f"{c}_prev"] = prevision(d[c], n, met)
        d[f"{c}_prev"] = d[f"{c}_prev"].fillna(0.0)   # primer día sin historia: previsión plana, no se opera
    # Diferencial de cada subasta intradiaria frente al diario (IDA1 15:00 de D-1, IDA2 22:00 de D-1 e IDA3
    # 10:00 de D: en todas, el último diferencial completo conocido es el de D-1).
    for k in ("ida1", "ida2", "ida3"):
        d[f"{k}_dif_prev"] = prevision(d[k] - d["da"], n, met)
    return d
