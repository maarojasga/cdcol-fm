"""Resumen por mes de las capas de incertidumbre de una zona ya calculada."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from cdcol_fm.ard.escritura import PRODUCTO


def _leer(ruta: Path) -> np.ndarray:
    import rioxarray

    capa = rioxarray.open_rasterio(ruta, masked=True)
    return np.asarray(capa).ravel()


def resumen_markdown(destino: Path, zona: str) -> str:
    filas = [
        "| Mes | Obs. S2 válidas (media) | Píxeles sin ninguna válida | "
        "Días desde vista clara (mediana) | Nube (% de obs.) | Pasos S1 (media) |",
        "|---|---|---|---|---|---|",
    ]
    for carpeta in sorted((destino / zona / PRODUCTO).glob("*-*")):
        n = _leer(carpeta / "n_validas_s2.tif")
        dias = _leer(carpeta / "dias_desde_clara.tif")
        nube = _leer(carpeta / "prob_nube.tif")
        s1 = _leer(carpeta / "n_adq_s1.tif")
        sin = 100 * np.mean(n == 0)
        filas.append(
            f"| {carpeta.name} | {np.nanmean(n):.1f} | {sin:.0f} % | "
            f"{np.nanmedian(dias):.0f} | {np.nanmean(nube):.0f} | {np.nanmean(s1):.1f} |"
        )
    return "\n".join(filas)
