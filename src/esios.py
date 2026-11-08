"""Cliente mínimo de la API de ESIOS (REE). Solo lectura."""
import os
import time

import pandas as pd
import requests

BASE = "https://api.esios.ree.es"


def _paso_horas(tiempo, idx):
    """Duración del periodo de la serie en horas, según el metadato «tiempo» de ESIOS
    (Cinco minutos, Quince minutos, Hora, Día) o, si falta, según el índice."""
    t = (tiempo or "").lower()
    for clave, h in (("cinco", 1 / 12), ("diez", 1 / 6), ("quince", 0.25), ("hora", 1.0), ("día", 24.0), ("dia", 24.0)):
        if clave in t:
            return h
    if len(idx) > 1:
        return float(pd.Series(idx).diff().dropna().median() / pd.Timedelta(hours=1))
    return 0.25


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
        """Devuelve (nombre_indicador, Serie con índice UTC) en la unidad de PANEL:
        precios en su unidad, potencias en MW y energías convertidas a MW medios.

        Se piden los datos CRUDOS (sin time_trunc) y se agregan aquí, porque ESIOS
        agrega por defecto SUMANDO: la demanda o la generación de 5 minutos salían
        multiplicadas por tres. Validado contra las tablas de UNEF (semanas 42 y 43).
          · magnitud «Energía» (MWh por periodo) -> MW = MWh / horas del periodo
            (602, 605-607, 680, 681, 674, 675 son MWh por cuarto: x4; 1442 es horario: x1).
          · resolución de 5 minutos -> media de cada cuarto de hora.
          · resolución horaria -> se deja horaria (el análisis la repite en los 4 cuartos).
          · zona: España (3) y, si no hay, Península (8741); nunca la geo más frecuente,
            que en los intradiarios podía ser Portugal.
        `fin` es exclusivo (ESIOS lo trata como inclusivo y devolvía el cuarto siguiente).
        """
        params = {"start_date": inicio.isoformat(), "end_date": fin.isoformat()}
        j = self._get(f"/indicators/{ind_id}", params)
        ind = j["indicator"]
        nombre = ind.get("name", "")
        self.ultima_meta = {
            "magnitud": ", ".join(m.get("name", "") for m in ind.get("magnitud", []) or []),
            "tiempo": ", ".join(m.get("name", "") for m in ind.get("tiempo", []) or []),
        }
        df = pd.DataFrame(ind.get("values", []))
        if df.empty:
            return nombre, pd.Series(dtype=float)
        if "geo_id" in df.columns and df["geo_id"].nunique() > 1:
            elegido = None
            for g in list(geos or []) + [3, 8741]:
                if (df["geo_id"] == g).any():
                    elegido = g
                    break
            if elegido is None:
                elegido = df["geo_id"].value_counts().idxmax()
            df = df[df["geo_id"] == elegido]
        t = pd.to_datetime(df["datetime_utc"], utc=True)
        s = pd.Series(df["value"].astype(float).values, index=t).sort_index()
        s = s.groupby(level=0).mean()
        s = s[(s.index >= inicio.tz_convert("UTC")) & (s.index < fin.tz_convert("UTC"))]
        if s.empty:
            return nombre, s
        paso_h = _paso_horas(self.ultima_meta["tiempo"], s.index)
        if "energ" in self.ultima_meta["magnitud"].lower():
            s = s / paso_h                                  # MWh por periodo -> MW medios
        if paso_h < 0.25 - 1e-9:                            # 5 minutos -> cuarto de hora
            s = s.resample("15min").mean()
        return nombre, s

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
