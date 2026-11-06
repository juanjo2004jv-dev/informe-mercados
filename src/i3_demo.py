"""Tabla I3 sintética (mismo formato que produce src/i3.py) para probar el diseño.
Magnitudes calibradas con una semana real de referencia; los números NO son reales."""
import numpy as np
import pandas as pd

PBF_SEMANA = {  # MWh/semana
    "Eólica": 1385961, "Solar fotovoltaica": 1247111, "Nuclear": 1114407, "Hidráulica": 417630,
    "Cogeneración": 249395, "Turbinación bombeo": 116761, "Solar térmica": 102048, "Ciclo combinado": 101521,
    "Otras renovables": 86497, "Híbrida renovable": 31554, "Residuos no renovables": 31018,
    "Híbrida renovable-almacenamiento": 22855, "Carbón": 14188, "Almacenamiento generación": 590,
    "Almacenamiento consumo": -2780, "Consumo bombeo": -189398,
}
RENOV = {"Eólica", "Solar fotovoltaica", "Solar térmica", "Otras renovables", "Híbrida renovable", "Híbrida renovable-almacenamiento"}
CICLO = {"Ciclo combinado": 1.0}
TIPOS = ["RSI", "SOT", "COT", "SCA", "RTD", "SCB"]


def semana(dias, precio_dia, seed=3):
    rng = np.random.default_rng(seed)
    filas = []

    def add(f, m, t, mag, v, fase="", tip="", sen=""):
        filas.append(dict(fecha=pd.Timestamp(f), mercado=m, tecnologia=t, magnitud=mag, fase=fase, tipologia=tip, sentido=sen, valor=float(v)))

    for i, d in enumerate(dias):
        pd_ = precio_dia[i]
        for t, w in PBF_SEMANA.items():
            pbf = w / 7 * rng.uniform(0.85, 1.15)
            bil = abs(pbf) * (0.25 if t == "Eólica" else 0.18 if t == "Solar fotovoltaica" else 0.0 if t in ("Solar térmica",) else 0.3) if pbf > 0 else 0
            dia_ = pbf - bil if pbf > 0 else pbf
            add(d, "PBF", t, "energia", pbf)
            add(d, "Bilaterales", t, "energia", bil)
            add(d, "Diario", t, "energia", dia_)
            cap = {"Solar fotovoltaica": 0.45, "Eólica": 0.78}.get(t, 1.0)
            add(d, "Diario", t, "ingreso", dia_ * pd_ * cap)
            # restricciones de la fase I (subir/bajar)
            if t in RENOV and pbf > 0:
                baja = -pbf * {"Solar fotovoltaica": 0.066, "Solar térmica": 0.02, "Eólica": 0.003}.get(t, 0.004) * rng.uniform(0.4, 1.8)
                sube = abs(baja) * 0.02
            elif t == "Ciclo combinado":
                baja, sube = -2000 * rng.uniform(0.5, 1.5), 74000 * rng.uniform(0.7, 1.3)
            elif t in ("Hidráulica", "Turbinación bombeo", "Nuclear"):
                baja, sube = -abs(pbf) * 0.002, abs(pbf) * 0.01 if t != "Nuclear" else 0
            else:
                baja, sube = 0.0, 0.0
            tips = TIPOS if t == "Ciclo combinado" else ["N/A"]
            for tp in tips:
                f_ = 1 / len(tips)
                if sube:
                    add(d, "Restricciones MD", t, "energia", sube * f_, "MD · Fase I", tp, "Subir")
                    add(d, "Restricciones MD", t, "ingreso", sube * f_ * (340 + rng.normal(0, 15)), "MD · Fase I", tp, "Subir")
                    if tp in ("COT", "SOT"):
                        add(d, "Restricciones MD", t, "energia_x_spot", sube * f_ * pd_ * 0.85, "MD · Fase I", tp, "Subir")
            if baja:
                add(d, "Restricciones MD", t, "energia", baja, "MD · Fase I", "N/A", "Bajar")
                add(d, "Restricciones MD", t, "ingreso", baja * (40 + rng.normal(0, 5)) * -1 * -1 * (1 if t in RENOV else 0.0), "MD · Fase I", "N/A", "Bajar")
        # fase II (reequilibrio), tiempo real, intradiarios, terciaria
        for t in ("Ciclo combinado", "Hidráulica", "Turbinación bombeo"):
            add(d, "Restricciones MD", t, "energia", -(60000 * rng.uniform(0.4, 1.4)) / (3 if t != "Ciclo combinado" else 1), "MD · Fase II", "N/A", "Bajar")
        for t in ("Solar fotovoltaica", "Eólica", "Solar térmica", "Ciclo combinado"):
            tr_b = -{"Solar fotovoltaica": 1700, "Eólica": 400, "Solar térmica": 0, "Ciclo combinado": 150}[t] * rng.uniform(0.5, 1.5)
            if tr_b:
                add(d, "Restricciones TR", t, "energia", tr_b, "Tiempo real", "RSI", "Bajar")
                add(d, "Restricciones TR", t, "ingreso", tr_b * -55 * -1 if t == "Solar fotovoltaica" else tr_b * 9, "Tiempo real", "RSI", "Bajar")
            if t == "Ciclo combinado":
                add(d, "Restricciones TR", t, "energia", 8600 * rng.uniform(0.7, 1.3), "Tiempo real", "SOT", "Subir")
                add(d, "Restricciones TR", t, "ingreso", 8600 * 340, "Tiempo real", "SOT", "Subir")
        for t in ("Solar fotovoltaica", "Eólica", "Ciclo combinado", "Hidráulica", "Solar térmica"):
            sg = {"Solar fotovoltaica": -4100, "Eólica": -3400, "Ciclo combinado": 10500, "Hidráulica": 1500, "Solar térmica": -120}[t]
            ida = sg * 0.8
            for k, n_ in ((1, 0.4), (2, 0.4), (3, 0.2)):
                add(d, f"Intradiario {k}", t, "energia", ida * n_ * rng.uniform(0.6, 1.4), "", "", "Subir" if ida > 0 else "Bajar")
                add(d, f"Intradiario {k}", t, "ingreso", ida * n_ * pd_ * rng.uniform(-0.4, 0.4), "", "", "")
            add(d, "Terciaria", t, "energia", sg * 0.2, "", "", "Subir" if sg > 0 else "Bajar")
            add(d, "Terciaria", t, "ingreso", sg * 0.2 * pd_ * -0.3, "", "", "")
    df = pd.DataFrame(filas)
    # programas: PDVP, PHF, P48 coherentes con los flujos (cierra por construcción)
    g = df.copy()
    rows = []
    for (f, t), x in g[g["magnitud"] == "energia"].groupby(["fecha", "tecnologia"]):
        pbf = x[x["mercado"] == "PBF"]["valor"].sum()
        r_md = x[x["mercado"] == "Restricciones MD"]["valor"].sum()
        ida = x[x["mercado"].str.startswith("Intradiario")]["valor"].sum()
        tr = x[x["mercado"] == "Restricciones TR"]["valor"].sum()
        te = x[x["mercado"] == "Terciaria"]["valor"].sum()
        pdvp = pbf + r_md
        phf = pdvp + ida
        p48 = phf + tr + te
        for m, v in (("PDVP", pdvp), ("PHF", phf), ("P48", p48)):
            rows.append(dict(fecha=f, mercado=m, tecnologia=t, magnitud="energia", fase="", tipologia="", sentido="", valor=v))
    # el PDVP/PHF anteriores quedan donde el flujo de restricciones MD ya incluye fase II
    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)


def historico(desde, hasta, seed=11):
    """COT/SOT diarios sintéticos desde 2025-01-01 (para la operación reforzada)."""
    rng = np.random.default_rng(seed)
    dias = pd.date_range(desde, hasta, freq="D")
    filas = []
    apagon = pd.Timestamp("2025-04-28")
    for d in dias:
        if d == pd.Timestamp("2025-04-29"):
            continue
        post = d > apagon
        base_cot = 1.5e6 if not post else rng.uniform(3.2e6, 4.6e6)
        base_sot = 2.2e6 if not post else rng.uniform(2.4e6, 3.6e6)
        for tip, ing in (("COT", base_cot * rng.uniform(0.8, 1.2)), ("SOT", base_sot * rng.uniform(0.8, 1.2))):
            reparto = {"Ciclo combinado": 0.986, "Nuclear": 0.012, "Hidráulica": 0.0015, "Turbinación bombeo": 0.0005}
            for t, w in reparto.items():
                e = ing * w / 330
                filas.append(dict(fecha=d, mercado="Restricciones MD", tecnologia=t, magnitud="ingreso", fase="MD · Fase I", tipologia=tip, sentido="Subir", valor=ing * w))
                filas.append(dict(fecha=d, mercado="Restricciones MD", tecnologia=t, magnitud="energia", fase="MD · Fase I", tipologia=tip, sentido="Subir", valor=e))
                filas.append(dict(fecha=d, mercado="Restricciones MD", tecnologia=t, magnitud="energia_x_spot", fase="MD · Fase I", tipologia=tip, sentido="Subir", valor=e * rng.uniform(80, 150) * 0.9))
    return pd.DataFrame(filas)
