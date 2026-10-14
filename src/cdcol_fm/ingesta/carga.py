"""Carga de ítems STAC en la grilla del país con ``odc-stac``."""

from __future__ import annotations

from typing import Any

import xarray as xr

from cdcol_fm.config import Pais, Zona
from cdcol_fm.fuentes.stac import RENOMBRE_S2, S1_RTC, S2_L2A


def grilla_destino(zona: Zona, pais: Pais, geobox: Any = None) -> dict[str, Any]:
    """Argumentos de ``odc.stac.load`` para la grilla: el GeoBox de un bloque o el bbox."""
    if geobox is not None:
        return {"geobox": geobox}
    return {"bbox": zona.bbox, "crs": pais.grilla.crs, "resolution": pais.grilla.resolucion_m}


def _cargar(
    items: list[Any], bandas: tuple[str, ...], zona: Zona, pais: Pais, geobox: Any = None
) -> xr.Dataset:
    import odc.stac

    return odc.stac.load(
        items,
        bands=list(bandas),
        **grilla_destino(zona, pais, geobox),
        groupby="solar_day",  # une teselas del mismo paso del satélite
        chunks={"x": 1024, "y": 1024},
        fail_on_error=True,
    )


def cargar_s2(items: list[Any], zona: Zona, pais: Pais, geobox: Any = None) -> xr.Dataset:
    ds = _cargar(items, S2_L2A.bandas, zona, pais, geobox)
    return ds.rename({k: v for k, v in RENOMBRE_S2.items() if k in ds})


def cargar_s1(items: list[Any], zona: Zona, pais: Pais, geobox: Any = None) -> xr.Dataset:
    ds = _cargar(items, S1_RTC.bandas, zona, pais, geobox)
    return ds.rename({"vv": "VV", "vh": "VH"})
