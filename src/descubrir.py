"""Busca indicadores de ESIOS por texto:  python -m src.descubrir fotovoltaica
o sondea IDs concretos (cobertura de la última semana):  python -m src.descubrir ids:630,631,2197"""
import sys
from datetime import date, timedelta

import pandas as pd

from .esios import Esios

if __name__ == "__main__":
    texto = " ".join(sys.argv[1:]).strip()
    if not texto:
        sys.exit("Escribe una palabra a buscar, p. ej.: fotovoltaica")
    cli = Esios()
    if texto.startswith("ids:"):
        fin = pd.Timestamp(date.today() - timedelta(days=2)).tz_localize("Europe/Madrid")
        ini = fin - pd.Timedelta(days=7)
        for i in [int(x) for x in texto[4:].split(",") if x.strip()]:
            try:
                nombre, s = cli.serie(i, ini, fin, [3, 8741])
                print(f"{i:>6}  {len(s):>4} datos  {nombre}")
            except Exception as e:
                print(f"{i:>6}  ERROR {str(e)[:80]}")
        sys.exit(0)
    res = cli.buscar(texto)
    print(f"{len(res)} indicadores contienen '{texto}':\n")
    for i, n in sorted(res):
        print(f"{i:>6}  {n}")
