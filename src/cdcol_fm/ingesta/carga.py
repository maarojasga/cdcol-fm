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


def desfase_dn(items: list[Any], asset: str) -> int:
    """Desfase en DN que declara ``raster:bands`` del asset (p. ej. -1000 desde la baseline
    04.00). Todos los ítems deben declarar el mismo: si no, mezclar escenas daría basura."""
    desfases = set()
    for it in items:
        banda = (it.assets[asset].extra_fields.get("raster:bands") or [{}])[0]
        escala = banda.get("scale", 1.0)
        desfases.add(round(banda.get("offset", 0.0) / escala))
    if len(desfases) > 1:
        raise ValueError(f"{asset}: ítems con desfases distintos {sorted(desfases)}")
    return desfases.pop() if desfases else 0


def quitar_desfase(capa: xr.DataArray, desfase: int) -> xr.DataArray:
    """Reflectancia × 10⁴ sin desfase, en uint16. 0 sigue siendo sin dato; lo que quedaría
    ≤ 0 (agua oscura) se recorta a 1 para no confundirlo con él."""
    if desfase == 0:
        return capa
    corregida = (capa.astype("int32") + desfase).clip(min=1)
    return corregida.where(capa != 0, 0).astype("uint16")


def cargar_s2(items: list[Any], zona: Zona, pais: Pais, geobox: Any = None) -> xr.Dataset:
    """S2 L2A en reflectancia × 10⁴ sin el desfase de las baselines ≥ 04.00, que es lo que
    esperan los modelos base (ADR 0004) y lo que dice el producto ARD."""
    ds = _cargar(items, S2_L2A.bandas, zona, pais, geobox)
    for asset in RENOMBRE_S2:
        if asset in ds and asset != "scl":
            ds[asset] = quitar_desfase(ds[asset], desfase_dn(items, asset))
    return ds.rename({k: v for k, v in RENOMBRE_S2.items() if k in ds})


def cargar_s1(items: list[Any], zona: Zona, pais: Pais, geobox: Any = None) -> xr.Dataset:
    ds = _cargar(items, S1_RTC.bandas, zona, pais, geobox)
    return ds.rename({"vv": "VV", "vh": "VH"})
