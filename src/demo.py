"""Datos sintéticos para probar el diseño sin token de ESIOS."""
import numpy as np
import pandas as pd

TZ = "Europe/Madrid"


def generar(idx, cfg, seed=7):
    rng = np.random.default_rng(seed)
    loc = idx.tz_convert(TZ)
    h = np.asarray(loc.hour + loc.minute / 60.0)
    dia = np.asarray(loc.normalize().asi8 // (24 * 3600 * 10**9))  # un número por día
    uniq, inv = np.unique(dia, return_inverse=True)
    desplaz = rng.normal(0, 28, len(uniq))[inv]
    sol = np.clip(rng.normal(1.0, 0.35, len(uniq)), 0.2, 1.6)[inv]
    g = lambda c, w: np.exp(-(((h - c) / w) ** 2))
    spot = 105 + desplaz + 125 * g(21, 2.2) + 55 * g(8.5, 1.5) - 135 * sol * g(14, 3.0) + rng.normal(0, 3, len(h))
    spot = np.round(np.clip(spot, -8, 330), 2)
    solar = np.clip(14500 * sol * g(14, 3.2) + rng.normal(0, 120, len(h)), 0, None)
    eolica = np.clip(6500 + 2500 * np.sin(np.arange(len(h)) / 230) + rng.normal(0, 150, len(h)), 500, None)
    real = 26000 + 6500 * g(14, 4.5) + 5000 * g(21, 2.5) + rng.normal(0, 150, len(h))
    mk = lambda v: pd.Series(v, index=idx)
    d = {
        "spot": mk(spot),
        "demanda_real": mk(real),
        "demanda_prevista": mk(real * (1 + rng.normal(0, 0.012, len(h)))),
        "demanda_programada": mk(real * (1 + rng.normal(-0.01, 0.02, len(h)))),
    }
    for k, v in cfg.get("opcionales", {}).items():
        t = v.get("tipo")
        if k == "gen_solar_fv":
            d[k] = mk(solar)
        elif k == "gen_eolica":
            d[k] = mk(eolica)
        elif t == "precio":
            off = {"afrr_subir": 30, "afrr_bajar": -25, "mfrr_subir": 40, "mfrr_bajar": -30}.get(k, -1)
            d[k] = mk(spot + off + rng.normal(0, 7, len(h)))
        elif t == "banda_precio":
            d[k] = mk(np.clip(8 + 14 * g(21, 2) + rng.normal(0, 2, len(h)), 0.2, None))
        elif t == "banda_mw":
            d[k] = mk(1000 + 450 * g(13, 5) + rng.normal(0, 25, len(h)))
        elif t == "energia":
            base = 21000 if k == "casada_diario" else 1500
            d[k] = mk(np.clip(base * (0.75 + 0.35 * g(14, 5)) + rng.normal(0, base * 0.03, len(h)), 0, None))
    meta = {k: {"nombre": k, "id": "—", "api": "sintético"} for k in d}
    return d, meta
