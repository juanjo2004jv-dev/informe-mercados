"""Cliente mínimo de la API de ESIOS (REE). Solo lectura."""
import os
import time

import pandas as pd
import requests

BASE = "https://api.esios.ree.es"


class Esios:
    def __init__(self, token=None):
        self.token = token or os.environ.get("ESIOS_TOKEN")
        if not self.token:
            raise RuntimeError(
                "Falta el token de ESIOS. Guárdalo como secreto ESIOS_TOKEN en GitHub."
            )
        self.s = requests.Session()
        self.s.headers.update(
            {
                "Accept": "application/json; application/vnd.esios-api-v1+json",
                "Content-Type": "application/json",
                "x-api-key": self.token,
            }
        )

    def _get(self, ruta, params=None, intentos=4):
        ultimo = None
        for i in range(intentos):
            try:
                r = self.s.get(BASE + ruta, params=params, timeout=90)
            except requests.RequestException as e:  # red caída, timeout...
                ultimo = e
                time.sleep(3 * 2**i)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                ultimo = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(3 * 2**i)
                continue
            r.raise_for_status()
        raise RuntimeError(f"ESIOS no responde en {ruta}: {ultimo}")

    def serie(self, ind_id, inicio, fin, geos=None):
        """Devuelve (nombre_indicador, Serie con índice UTC)."""
        params = {
            "start_date": inicio.isoformat(),
            "end_date": fin.isoformat(),
            "time_trunc": "fifteen_minutes",
        }
        try:
            j = self._get(f"/indicators/{ind_id}", params)
        except requests.HTTPError:
            params.pop("time_trunc")  # algún indicador no admite cuartohorario
            j = self._get(f"/indicators/{ind_id}", params)
        ind = j["indicator"]
        nombre = ind.get("name", "")
        df = pd.DataFrame(ind.get("values", []))
        if df.empty:
            return nombre, pd.Series(dtype=float)
        if "geo_id" in df.columns and df["geo_id"].nunique() > 1:
            elegido = None
            for g in geos or []:
                if (df["geo_id"] == g).any():
                    elegido = g
                    break
            if elegido is None:
                elegido = df["geo_id"].value_counts().idxmax()
            df = df[df["geo_id"] == elegido]
        t = pd.to_datetime(df["datetime_utc"], utc=True)
        s = pd.Series(df["value"].astype(float).values, index=t).sort_index()
        return nombre, s.groupby(level=0).mean()

    def buscar(self, texto):
        """Lista de (id, nombre) de indicadores cuyo nombre contiene el texto."""
        j = self._get("/indicators")
        t = texto.lower()
        return [
            (i["id"], i.get("name", ""))
            for i in j.get("indicators", [])
            if t in i.get("name", "").lower()
        ]

    def listar(self):
        """Todos los indicadores: lista de (id, nombre)."""
        j = self._get("/indicators")
        return [(i["id"], i.get("name", "")) for i in j.get("indicators", [])]
