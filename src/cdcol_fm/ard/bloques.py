"""Bloques: teselas fijas de la grilla nacional en las que se parte una zona grande.

Un bloque mide ``tesela_px`` píxeles de lado y su esquina cae en un múltiplo de su tamaño,
así que el mismo bloque tiene la misma grilla en cualquier zona que lo toque. Su id es
``x{columna}_y{fila}`` con columna = floor(x / lado) y fila = floor(y / lado).
"""

from __future__ import annotations

import calendar
import math
import re
from dataclasses import dataclass
from typing import Any

from cdcol_fm.config import Pais, Zona

_PATRON_ID = re.compile(r"^x(-?\d+)_y(-?\d+)$")


@dataclass(frozen=True)
class Bloque:
    id: str
    columna: int
    fila: int
    lado_m: float
    pais: Pais

    @property
    def limites(self) -> tuple[float, float, float, float]:
        """(oeste, sur, este, norte) en el CRS del país."""
        x0, y0 = self.columna * self.lado_m, self.fila * self.lado_m
        return (x0, y0, x0 + self.lado_m, y0 + self.lado_m)

    def geobox(self) -> Any:
        from affine import Affine
        from odc.geo.geobox import GeoBox

        res = self.pais.grilla.resolucion_m
        n = self.pais.grilla.tesela_px
        x0, _, _, y1 = self.limites
        return GeoBox((n, n), Affine(res, 0, x0, 0, -res, y1), self.pais.grilla.crs)

    def bbox_geografico(self) -> tuple[float, float, float, float]:
        b = self.geobox().geographic_extent.boundingbox
        return (b.left, b.bottom, b.right, b.top)


def _lado(pais: Pais) -> float:
    return pais.grilla.resolucion_m * pais.grilla.tesela_px


def bloque(id_bloque: str, pais: Pais) -> Bloque:
    coincidencia = _PATRON_ID.match(id_bloque)
    if not coincidencia:
        raise ValueError(f"id de bloque inválido: {id_bloque} (se espera x<col>_y<fila>)")
    col, fila = int(coincidencia.group(1)), int(coincidencia.group(2))
    return Bloque(id_bloque, col, fila, _lado(pais), pais)


def bloques_de_zona(zona: Zona, pais: Pais) -> list[Bloque]:
    """Bloques que tocan la zona (su bbox reproyectado, no solo el rectángulo envolvente)."""
    from odc.geo.geom import box

    huella = box(*zona.bbox, "EPSG:4326").to_crs(pais.grilla.crs)
    b = huella.boundingbox
    lado = _lado(pais)
    salida = []
    for fila in range(math.floor(b.bottom / lado), math.ceil(b.top / lado)):
        for col in range(math.floor(b.left / lado), math.ceil(b.right / lado)):
            candidato = Bloque(f"x{col}_y{fila}", col, fila, lado, pais)
            if box(*candidato.limites, pais.grilla.crs).intersects(huella):
                salida.append(candidato)
    return salida


def recortar_zona(
    zona: Zona,
    bloque_: Bloque | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> Zona:
    """La zona limitada a un bloque y a un rango de meses ``AAAA-MM`` (ambos opcionales)."""
    cambios: dict[str, Any] = {}
    if bloque_ is not None:
        cambios["bbox"] = bloque_.bbox_geografico()
    if desde is not None:
        cambios["fecha_inicio"] = max(zona.fecha_inicio, f"{desde}-01")
    if hasta is not None:
        anio, mes = (int(p) for p in hasta.split("-"))
        ultimo = calendar.monthrange(anio, mes)[1]
        cambios["fecha_fin"] = min(zona.fecha_fin, f"{hasta}-{ultimo:02d}")
    return Zona.model_validate({**zona.model_dump(), **cambios})


def con_historia(zona: Zona, meses: int) -> Zona:
    """La zona con ``fecha_inicio`` corrida ``meses`` hacia atrás (al día 1 de ese mes).

    Para S2: ``dias_desde_clara`` de un mes mira las observaciones de los meses anteriores.
    """
    anio, mes = (int(p) for p in zona.fecha_inicio[:7].split("-"))
    total = anio * 12 + (mes - 1) - meses
    inicio = f"{total // 12:04d}-{total % 12 + 1:02d}-01"
    return Zona.model_validate({**zona.model_dump(), "fecha_inicio": inicio})
