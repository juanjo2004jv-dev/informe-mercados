"""Auditoría de fuentes: vuelca los datos CRUDOS de ESIOS (sin agregar) y el I3 de unos días
para poder validar, fuera de GitHub, cómo se toman las series (unidades, resolución, zona).

python -m src.auditoria --desde 2026-10-12 --hasta 2026-11-02
Escribe data/auditoria/ind_<id>.json.gz, data/auditoria/agregacion.json e i3_<dia>.zip.
No interviene ninguna IA: solo descarga y guarda.
"""
import argparse
import gzip
import json
from datetime import date
from pathlib import Path

import pandas as pd

from .esios import Esios

RAIZ = Path(__file__).resolve().parent.parent
OUT = RAIZ / "data" / "auditoria"
TZ = "Europe/Madrid"

IDS = [600, 612, 613, 614, 1727, 602, 605, 606, 607, 1442, 682, 683, 680, 681, 2197, 2196,
       10388, 10463, 630, 631, 632, 633, 634, 2130, 674, 675, 676, 677,
       10394, 10395, 10396, 10397, 10398, 10399, 1293, 544, 545, 551, 1295]


def crudo(cli, i, ini, fin, extra=None):
    p = {"start_date": ini.isoformat(), "end_date": fin.isoformat()}
    p.update(extra or {})
    return cli._get(f"/indicators/{i}", p)["indicator"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", required=True)
    ap.add_argument("--hasta", required=True)
    ap.add_argument("--i3", default="")
    ap.add_argument("--ids", default="", help="IDs separados por coma; vacío = lista por defecto")
    ap.add_argument("--agregacion", action="store_true", help="prueba también time_trunc/time_agg")
    a = ap.parse_args()
    ids = [int(x) for x in a.ids.split(",") if x.strip()] or IDS
    OUT.mkdir(parents=True, exist_ok=True)
    cli = Esios()
    ini = pd.Timestamp(a.desde).tz_localize(TZ)
    fin = pd.Timestamp(a.hasta).tz_localize(TZ)
    resumen = {}
    for i in ids:
        try:
            ind = crudo(cli, i, ini, fin)
        except Exception as e:
            resumen[i] = {"error": str(e)[:200]}
            continue
        vals = [{k: v.get(k) for k in ("datetime_utc", "datetime", "value", "geo_id", "geo_name")} for v in ind.get("values", [])]
        meta = {k: v for k, v in ind.items() if k != "values"}
        with gzip.open(OUT / f"ind_{i}.json.gz", "wt", encoding="utf-8") as f:
            json.dump({"meta": meta, "values": vals}, f, ensure_ascii=False)
        resumen[i] = {"nombre": ind.get("name"), "n": len(vals), "magnitud": ind.get("magnitud"), "tiempo": ind.get("tiempo"),
                      "geos": sorted({(v["geo_id"], v["geo_name"]) for v in vals}, key=str)[:12]}
    # cómo agrega ESIOS con time_trunc (con y sin time_agg) en un día
    dia_i = pd.Timestamp("2026-10-22").tz_localize(TZ)
    dia_f = pd.Timestamp("2026-10-23").tz_localize(TZ)
    agg = {}
    for i in ((1293, 551, 10388, 602, 680, 600) if a.agregacion else ()):
        agg[i] = {}
        for nombre, extra in (("crudo", {}), ("qh", {"time_trunc": "fifteen_minutes"}),
                              ("qh_avg", {"time_trunc": "fifteen_minutes", "time_agg": "average"}),
                              ("qh_sum", {"time_trunc": "fifteen_minutes", "time_agg": "sum"})):
            try:
                ind = crudo(cli, i, dia_i, dia_f, extra)
                v = ind.get("values", [])
                agg[i][nombre] = {"n": len(v), "primeros": [(x.get("datetime_utc"), x.get("geo_id"), x.get("value")) for x in v[:8]]}
            except Exception as e:
                agg[i][nombre] = {"error": str(e)[:200]}
    previo = json.loads((OUT / "resumen.json").read_text(encoding="utf-8")) if (OUT / "resumen.json").exists() else {}
    previo.update({str(k): v for k, v in resumen.items()})
    (OUT / "resumen.json").write_text(json.dumps(previo, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if agg:
        (OUT / "agregacion.json").write_text(json.dumps(agg, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    from .i3 import descargar_dia

    for d in [x for x in a.i3.split(",") if x]:
        try:
            (OUT / f"i3_{d}.zip").write_bytes(descargar_dia(cli, date.fromisoformat(d)))
        except Exception as e:
            print("I3", d, e)
    print(json.dumps(resumen, ensure_ascii=False, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
