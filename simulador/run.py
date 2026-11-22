"""Orquestador del simulador de escenarios BESS.

  python -m simulador.run descargar --desde 2026-07 --hasta 2026-09
  python -m simulador.run simular --escenarios unef_a,unef_b,unef_c --desde 2026-07-01 --hasta 2026-10-01
  python -m simulador.run validar
"""
import argparse
import copy
import json
import os
from pathlib import Path

import pandas as pd
import yaml

from . import datos, motor

RAIZ = Path(__file__).resolve().parent.parent
RES = RAIZ / "data" / "simulador" / "resultados"
LINEAS = ["diario_bess", "diario_fv", "intradiario", "afrr_banda", "afrr_activacion", "mfrr", "reposicion"]


def _fusion(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        out[k] = _fusion(out.get(k, {}), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def escenario(nombre):
    cfg = datos.cargar_config()
    with open(Path(__file__).parent / "escenarios" / f"{nombre}.yml", encoding="utf-8") as f:
        esc = yaml.safe_load(f)
    return _fusion(cfg, esc)


def resumen(md):
    s = os.environ.get("GITHUB_STEP_SUMMARY")
    print(md)
    if s:
        with open(s, "a", encoding="utf-8") as f:
            f.write(md + "\n")


def cmd_descargar(a):
    cfg = datos.cargar_config()
    cli = datos.Esios()
    tabla = {}
    for p in pd.period_range(a.desde, a.hasta, freq="M"):
        print(f"Descargando {p}…")
        tabla[str(p)] = datos.descargar_mes(p.year, p.month, cli, cfg)
    df = pd.DataFrame(tabla)
    (RAIZ / "data" / "simulador").mkdir(parents=True, exist_ok=True)
    df.to_csv(RAIZ / "data" / "simulador" / "cobertura.csv", float_format="%.4f")
    resumen("### Cobertura de las series (fracción de cuartos con dato)\n\n" + df.map(lambda v: f"{v:.1%}").to_markdown())


def cmd_simular(a):
    df = datos.leer(a.desde, a.hasta)
    for nombre in a.escenarios.split(","):
        cfg = escenario(nombre)
        d2, avisos = datos.completar(df, cfg)
        res, det = motor.simular(d2, cfg["activo"], cfg)
        norm = cfg["activo"]["p_poi_mw"] if cfg["normalizar_por"] == "poi" else cfg["activo"]["p_bess_mw"]
        res.index = pd.to_datetime(res.index)
        mens = res.groupby(res.index.to_period("M")).sum(numeric_only=True)
        eur = mens[[c for c in LINEAS + ["coste_ciclado", "ivpee"] if c in mens]] / norm
        eur["total"] = eur[[c for c in LINEAS if c in eur]].sum(axis=1)
        eur["ciclos_dia"] = mens["ciclos"] / res.groupby(res.index.to_period("M")).size()
        eur["apuntamiento"] = mens["ingreso_descarga"] / mens["mwh_descarga"].where(mens["mwh_descarga"] > 0)
        out = RES / nombre
        out.mkdir(parents=True, exist_ok=True)
        tramo = f"{a.desde}_{a.hasta}"
        res.to_csv(out / f"{tramo}_diario.csv", float_format="%.2f")
        eur.to_csv(out / f"{tramo}_mensual_eur_mw.csv", float_format="%.1f")
        det.to_csv(out / f"{tramo}_cuartos.csv.gz", float_format="%.3f")
        with open(out / f"{tramo}_avisos.json", "w", encoding="utf-8") as f:
            json.dump({"escenario": cfg.get("nombre", nombre), "avisos": avisos}, f, ensure_ascii=False, indent=1)
        resumen(f"### {cfg.get('nombre', nombre)} (€/MW)\n\n" + eur.round(0).to_markdown()
                + ("\n\nAvisos: " + " · ".join(avisos) if avisos else ""))


def cmd_validar(a):
    with open(Path(__file__).parent / "valores_dorados.yml", encoding="utf-8") as f:
        ref = yaml.safe_load(f)
    tol = ref["tolerancia_total"]
    filas, fallos = [], 0
    for esc, meses in ref["unef"].items():
        archivos = sorted((RES / esc).glob("*_mensual_eur_mw.csv"))
        if not archivos:
            continue
        nos = pd.concat(pd.read_csv(x, index_col=0) for x in archivos)
        nos = nos[~nos.index.duplicated(keep="last")]
        for mes, r in meses.items():
            if mes not in nos.index:
                continue
            fila = {"escenario": esc, "mes": mes}
            for k in ["total"] + LINEAS:
                if k in r:
                    fila[f"{k} UNEF"] = r[k]
                    fila[f"{k} nuestro"] = round(float(nos.loc[mes, k]))
            desv = fila["total nuestro"] / r["total"] - 1
            fila["desviación total"] = f"{desv:+.1%}"
            fila["ok"] = "✔" if abs(desv) <= tol else "⚠"
            fallos += abs(desv) > tol
            filas.append(fila)
    t = pd.DataFrame(filas)
    RES.mkdir(parents=True, exist_ok=True)
    t.to_csv(RES / "validacion_unef.csv", index=False)
    resumen("### Validación contra el UNEF BESS Index\n\n" + (t.to_markdown(index=False) if len(t) else "Sin datos"))
    print(f"Meses fuera de tolerancia (±{tol:.0%}): {fallos}")


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("descargar")
    d.add_argument("--desde", required=True)
    d.add_argument("--hasta", required=True)
    s = sp.add_parser("simular")
    s.add_argument("--escenarios", default="unef_a,unef_b,unef_c")
    s.add_argument("--desde", required=True)
    s.add_argument("--hasta", required=True)
    sp.add_parser("validar")
    a = p.parse_args()
    {"descargar": cmd_descargar, "simular": cmd_simular, "validar": cmd_validar}[a.cmd](a)


if __name__ == "__main__":
    main()
