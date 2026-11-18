"""Rasgos por píxel a partir del ARD mensual de un año."""

from __future__ import annotations

import numpy as np
import xarray as xr

from cdcol_fm.ard.bandas import BANDAS_S1, BANDAS_S2

CUANTILES = (0.1, 0.5, 0.9)


def ard_anual(serie: xr.Dataset) -> tuple[np.ndarray, list[str]]:
    """p10, mediana y p90 anuales de S2 y S1, ignorando meses sin dato.

    ``serie`` con dims (time, y, x). Devuelve (píxeles, rasgos) y los nombres. Las capas de
    incertidumbre no entran: en E01 sirven para estratificar, no para predecir.
    """
    columnas = []
    nombres = []
    for banda in BANDAS_S2 + BANDAS_S1:
        datos = serie[banda].astype("float32")
        if banda in BANDAS_S2:
            datos = datos.where(datos > 0)  # 0 es sin dato en las bandas S2
        q = datos.quantile(list(CUANTILES), dim="time", skipna=True)
        for cuantil in CUANTILES:
            columnas.append(np.asarray(q.sel(quantile=cuantil)).ravel())
            nombres.append(f"{banda}_p{int(cuantil * 100):02d}")
    return np.stack(columnas, axis=1), nombres


def n_validas_anual(serie: xr.Dataset) -> np.ndarray:
    """Observaciones S2 válidas en el año, por píxel (255 = sin dato cuenta como 0)."""
    n = serie["n_validas_s2"].where(serie["n_validas_s2"] != 255, 0)
    return np.asarray(n.sum("time")).ravel().astype("float32")
