"""Vuelca todos los indicadores de ESIOS a data/indicadores_esios.csv"""
import csv
from pathlib import Path

from .esios import Esios

if __name__ == "__main__":
    filas = sorted(Esios().listar())
    ruta = Path(__file__).resolve().parent.parent / "data" / "indicadores_esios.csv"
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "nombre"])
        w.writerows(filas)
    print(f"{len(filas)} indicadores guardados en {ruta}")
