"""Regla fija para elegir los bloques de un experimento (parte del pre-registro).

1. Solo bloques enteros dentro de la zona (``dentro >= DENTRO_MIN``).
2. Solo bloques mixtos: fracción de bosque de ESA WorldCover entre ``BOSQUE_MIN`` y
   ``BOSQUE_MAX``, para que cada bloque aporte las dos clases y bordes reales.
3. Los elegibles se ordenan de sur a norte y se parten en ``franjas`` del mismo tamaño; de cada
   franja se toman ``por_franja`` al azar con semilla fija. Así la muestra recorre el gradiente
   serranía → piedemonte → llanura y no se concentra en un solo paisaje.

WorldCover se usa solo para elegir: no es la referencia del experimento ni mira resultados.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from cdcol_fm.config import Pais, Zona

DENTRO_MIN = 0.99
BOSQUE_MIN = 0.15
BOSQUE_MAX = 0.85
REDUCCION = 8  # 1024 px → 128 px de 80 m: basta para estimar fracciones y carga rápido


@dataclass(frozen=True)
class Candidato:
    id: str
    columna: int
    fila: int
    dentro: float  # fracción del bloque dentro del bbox de la zona
    bosque: float  # fracción de bosque (WorldCover) en la parte con dato

    @property
    def elegible(self) -> bool:
        return self.dentro >= DENTRO_MIN and BOSQUE_MIN <= self.bosque <= BOSQUE_MAX


def elegir(
    candidatos: list[Candidato], franjas: int, por_franja: int, semilla: int = 0
) -> list[Candidato]:
    """Aplica los pasos 1-3 de la regla. Devuelve los elegidos ordenados por id."""
    elegibles = sorted((c for c in candidatos if c.elegible), key=lambda c: (c.fila, c.columna))
    if len(elegibles) < franjas * por_franja:
        raise ValueError(
            f"solo {len(elegibles)} bloques elegibles; hacen falta {franjas * por_franja}"
        )
    rng = np.random.default_rng(semilla)
    elegidos: list[Candidato] = []
    for franja in np.array_split(np.arange(len(elegibles)), franjas):
        for i in rng.choice(franja, size=por_franja, replace=False):
            elegidos.append(elegibles[int(i)])
    return sorted(elegidos, key=lambda c: c.id)


def candidatos_worldcover(zona: Zona, pais: Pais) -> list[Candidato]:
    """Fracción de bosque y de área dentro de la zona de cada bloque (red: Planetary Computer)."""
    import odc.stac
    from odc.geo.geom import box

    from cdcol_fm.ard.bloques import bloques_de_zona
    from cdcol_fm.fuentes.stac import WORLDCOVER, WORLDCOVER_BOSQUE, buscar

    items = buscar(WORLDCOVER, zona)
    if not items:
        raise RuntimeError(f"no hay WorldCover para {zona.id}")
    ultimo = max(it.datetime.year for it in items)
    items = [it for it in items if it.datetime.year == ultimo]
    huella = box(*zona.bbox, "EPSG:4326").to_crs(pais.grilla.crs)
    salida = []
    for b in bloques_de_zona(zona, pais):
        gb = b.geobox().zoom_out(REDUCCION)
        mapa: Any = odc.stac.load(items, bands=["map"], geobox=gb, resampling="nearest")
        clases = np.asarray(mapa["map"].isel(time=0))
        con_dato = clases > 0
        bosque = float((clases == WORLDCOVER_BOSQUE).sum() / max(con_dato.sum(), 1))
        celda = box(*b.limites, pais.grilla.crs)
        dentro = float(celda.intersection(huella).area / celda.area)
        salida.append(Candidato(b.id, b.columna, b.fila, dentro, bosque))
    return salida
