"""Búsqueda de escenas en catálogos STAC públicos.

Las imágenes no se copian: se leen de los buckets públicos de cada proveedor (ADR 0003).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cdcol_fm.config import Zona


@dataclass(frozen=True)
class Fuente:
    nombre: str
    url: str
    coleccion: str
    bandas: tuple[str, ...]
    firmar: bool = False  # Planetary Computer exige firmar los href (token SAS gratuito)
    atemporal: bool = False  # p. ej. el DEM: una sola fecha, no se filtra por el rango de la zona


S2_L2A = Fuente(
    nombre="s2",
    url="https://earth-search.aws.element84.com/v1",
    coleccion="sentinel-2-c1-l2a",
    # nombres de asset en Earth Search; se renombran a B02... al cargar
    bandas=(
        "blue",
        "green",
        "red",
        "rededge1",
        "rededge2",
        "rededge3",
        "nir",
        "nir08",
        "swir16",
        "swir22",
        "scl",
    ),
)

S1_RTC = Fuente(
    nombre="s1",
    url="https://planetarycomputer.microsoft.com/api/stac/v1",
    coleccion="sentinel-1-rtc",
    bandas=("vv", "vh"),
    firmar=True,
)

# Solo para comparar cobertura: los assets de GRD en Earth Search son "requester pays".
S1_GRD_ES = Fuente(
    nombre="s1-grd",
    url="https://earth-search.aws.element84.com/v1",
    coleccion="sentinel-1-grd",
    bandas=("vv", "vh"),
)

S1_GRD_PC = Fuente(
    nombre="s1-grd-pc",
    url="https://planetarycomputer.microsoft.com/api/stac/v1",
    coleccion="sentinel-1-grd",
    bandas=("vv", "vh"),
    firmar=True,
)

# Fuente elegida por Ale (12-oct-2026) para S1: GRD completo desde Copernicus Data Space.
# El catálogo es público; los datos (s3://eodata) requieren llaves S3 gratuitas de CDSE.
S1_GRD_CDSE = Fuente(
    nombre="s1-cdse",
    url="https://stac.dataspace.copernicus.eu/v1",
    coleccion="sentinel-1-grd",
    bandas=("vv", "vh"),
)

DEM_GLO30 = Fuente(
    nombre="dem",
    url="https://planetarycomputer.microsoft.com/api/stac/v1",
    coleccion="cop-dem-glo-30",
    bandas=("data",),
    firmar=True,
    atemporal=True,
)

# Asset de Earth Search → nombre de banda en el producto ARD.
RENOMBRE_S2 = {
    "blue": "B02",
    "green": "B03",
    "red": "B04",
    "rededge1": "B05",
    "rededge2": "B06",
    "rededge3": "B07",
    "nir": "B08",
    "nir08": "B8A",
    "swir16": "B11",
    "swir22": "B12",
    "scl": "SCL",
}


def buscar(fuente: Fuente, zona: Zona, max_items: int | None = None) -> list[Any]:
    """Ítems STAC de la fuente que tocan la zona en su rango de fechas."""
    import pystac_client

    modificador = None
    if fuente.firmar:
        import planetary_computer  # type: ignore[import-untyped]

        modificador = planetary_computer.sign_inplace
    cliente = pystac_client.Client.open(fuente.url, modifier=modificador)
    busqueda = cliente.search(
        collections=[fuente.coleccion],
        bbox=list(zona.bbox),
        datetime=None if fuente.atemporal else f"{zona.fecha_inicio}/{zona.fecha_fin}",
        max_items=max_items,
    )
    return list(busqueda.items())
