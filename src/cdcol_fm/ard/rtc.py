"""Corrección de relieve (RTC) de Sentinel-1 GRD con sarsen, directamente en la grilla del país.

sarsen escribe su salida en la grilla del DEM, así que el DEM se prepara ya recortado a la
zona y en la grilla nacional: la salida cae alineada con S2 sin remuestrear otra vez.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import xarray as xr

from cdcol_fm.config import Pais, Zona
from cdcol_fm.fuentes.stac import DEM_GLO30, buscar
from cdcol_fm.ingesta.carga import grilla_destino

# Aplanamiento gamma: el estándar para RTC (Small 2011); "nearest" es mucho más rápido.
RADIOMETRIA = "gamma_bilinear"


def preparar_dem(zona: Zona, pais: Pais, ruta: Path, geobox: Any = None) -> Path:
    """Copernicus GLO-30 remuestreado a la grilla nacional y recortado a la zona."""
    import odc.stac
    import rioxarray  # noqa: F401

    items = buscar(DEM_GLO30, zona)
    if not items:
        raise RuntimeError(f"No hay teselas GLO-30 para la zona {zona.id}")
    dem = odc.stac.load(
        items,
        bands=["data"],
        **grilla_destino(zona, pais, geobox),
        resampling="bilinear",
    )["data"].isel(time=0, drop=True)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    dem.astype("float32").rio.to_raster(ruta)
    return ruta


def rtc_escena(safe: Path, polarizacion: str, dem: Path, salida: Path) -> xr.DataArray:
    """gamma0 aplanado por relieve (lineal) de una polarización, en la grilla del DEM."""
    import sarsen

    producto = sarsen.Sentinel1SarProduct(str(safe), measurement_group=f"IW/{polarizacion.upper()}")
    return sarsen.terrain_correction(
        producto,
        dem_urlpath=str(dem),
        output_urlpath=str(salida),
        correct_radiometry=RADIOMETRIA,
        interp_method="linear",
    )


def cargar_s1_cdse(
    items: list[Any],
    zona: Zona,
    pais: Pais,
    trabajo: Path,
    avisar: Any = print,
    geobox: Any = None,
) -> xr.Dataset:
    """Serie S1 (VV, VH, lineal) corregida por relieve, en la grilla nacional."""
    import rioxarray

    from cdcol_fm.fuentes.cdse import descargar_safe, es_iw

    dem = preparar_dem(zona, pais, trabajo / "dem.tif", geobox)
    avisar(f"DEM GLO-30 listo en {pais.grilla.crs}")
    capas = []
    for item in sorted((it for it in items if es_iw(it)), key=lambda it: it.datetime):
        safe = descargar_safe(item, trabajo / "safe")
        pols = {}
        for pol in ("VV", "VH"):
            ruta = trabajo / "rtc" / f"{item.id}_{pol}.tif"
            ruta.parent.mkdir(parents=True, exist_ok=True)
            rtc_escena(safe, pol, dem, ruta)
            leida = rioxarray.open_rasterio(ruta, masked=True)
            assert isinstance(leida, xr.DataArray)
            pols[pol] = leida.squeeze("band", drop=True)
        # el SAFE pesa ~1-2 GB: se borra apenas queda el gamma0 del bloque (disco del runner: 14 GB)
        shutil.rmtree(safe, ignore_errors=True)
        capa = xr.Dataset(pols).expand_dims(time=[item.datetime.replace(tzinfo=None)])
        capas.append(capa)
        avisar(f"RTC {item.id}")
    serie = xr.concat(capas, dim="time")
    # varias escenas del mismo paso (cortes contiguos de la franja) → una sola fecha
    serie = serie.assign_coords(time=serie["time"].dt.floor("D"))
    return serie.groupby("time").mean(skipna=True)
