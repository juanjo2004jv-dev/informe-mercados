"""Busca indicadores de ESIOS por texto:  python -m src.descubrir fotovoltaica"""
import sys

from .esios import Esios

if __name__ == "__main__":
    texto = " ".join(sys.argv[1:]).strip()
    if not texto:
        sys.exit("Escribe una palabra a buscar, p. ej.: fotovoltaica")
    res = Esios().buscar(texto)
    print(f"{len(res)} indicadores contienen '{texto}':\n")
    for i, n in sorted(res):
        print(f"{i:>6}  {n}")
