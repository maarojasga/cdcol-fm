"""Corrección de relieve (RTC) de Sentinel-1 GRD con sarsen, directamente en la grilla del país.

sarsen escribe su salida en la grilla del DEM, así que el DEM se prepara ya recortado a la
zona y en la grilla nacional: la salida cae alineada con S2 sin remuestrear otra vez.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import xarray as xr

from cdcol_fm.config import Pais, Zona
from cdcol_fm.fuentes.stac import DEM_GLO30, buscar
from cdcol_fm.ingesta.carga import grilla_destino

# Aplanamiento gamma: el estándar para RTC (Small 2011); "nearest" es mucho más rápido.
RADIOMETRIA = "gamma_bilinear"
TROZO = 1024  # chunks por defecto de sarsen.terrain_correction
VENTANA = 2048  # lado (px) de cada corrida de sarsen; acota la memoria


def preparar_dem(zona: Zona, pais: Pais, ruta: Path, geobox: Any = None) -> Path:
    """Copernicus GLO-30 remuestreado a la grilla nacional y recortado a la zona."""
    import odc.stac
    import rioxarray  # noqa: F401

    if geobox is not None:
        # buscar las teselas del DEM que cubren la grilla pedida, que puede salirse de la zona
        b = geobox.geographic_extent.boundingbox
        zona = zona.model_copy(update={"bbox": (b.left, b.bottom, b.right, b.top)})
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


@dataclass(frozen=True)
class EscenaRTC:
    """Una escena S1 ya corregida: gamma0 lineal por polarización, en la grilla nacional."""

    item: Any
    rutas: dict[str, Path]


def geobox_zona(zona: Zona, pais: Pais) -> Any:
    """GeoBox de la zona con bordes en múltiplos de la resolución (alineado con los bloques)."""
    from odc.geo.geobox import GeoBox
    from odc.geo.geom import box

    huella = box(*zona.bbox, "EPSG:4326").to_crs(pais.grilla.crs)
    return GeoBox.from_bbox(
        huella.boundingbox, pais.grilla.crs, resolution=pais.grilla.resolucion_m
    )


def _recorte(item: Any, geobox: Any, pais: Pais) -> tuple[Any, Any] | None:
    """La parte de ``geobox`` que la escena cubre (y la huella de la escena), o None."""
    from odc.geo.geobox import GeoBox
    from odc.geo.geom import Geometry

    huella = Geometry(item.geometry, "EPSG:4326").to_crs(pais.grilla.crs)
    comun = huella.intersection(geobox.extent)
    if comun.is_empty:
        return None
    recorte = GeoBox.from_bbox(
        comun.boundingbox, pais.grilla.crs, resolution=pais.grilla.resolucion_m
    )
    # sarsen trabaja en trozos de 1024 px con un borde de 128: un último trozo más angosto que
    # el borde rompe dask. Se completa a múltiplos de 1024 (lo que sobra sale sin dato).
    alto, ancho = (-(-n // TROZO) * TROZO for n in recorte.shape)
    return GeoBox((alto, ancho), recorte.affine, recorte.crs), comun


def _ventanas(recorte: Any, huella: Any) -> list[tuple[int, int, Any]]:
    """Ventanas de ``VENTANA`` px del recorte que tocan la huella: (fila, columna, geobox)."""
    alto, ancho = recorte.shape
    salida = []
    for f in range(0, alto, VENTANA):
        for c in range(0, ancho, VENTANA):
            # GeoBox no recorta al pasarse del borde: se limita a mano
            sub = recorte[f : min(f + VENTANA, alto), c : min(c + VENTANA, ancho)]
            if sub.extent.intersects(huella):
                salida.append((f, c, sub))
    return salida


def rtc_escenas(
    items: list[Any],
    zona: Zona,
    pais: Pais,
    trabajo: Path,
    avisar: Any = print,
    geobox: Any = None,
) -> list[EscenaRTC]:
    """Baja y corrige cada escena una sola vez, recortada a la zona (o al ``geobox`` dado).

    La corrección corre por ventanas (la zona entera de una vez no cabe en la memoria del
    runner) y cada ventana se escribe en un solo raster por escena y polarización. Los
    bloques luego leen su parte de ese raster, sin volver a descargar nada.
    """
    import rasterio  # type: ignore[import-untyped]
    from rasterio.windows import Window  # type: ignore[import-untyped]

    from cdcol_fm.fuentes.cdse import descargar_safe, es_iw

    geobox = geobox if geobox is not None else geobox_zona(zona, pais)
    salida = []
    for item in sorted((it for it in items if es_iw(it)), key=lambda it: it.datetime):
        r = _recorte(item, geobox, pais)
        if r is None:
            continue
        recorte, huella = r
        ventanas = _ventanas(recorte, huella)
        safe = descargar_safe(item, trabajo / "safe")
        rutas = {}
        for pol in ("VV", "VH"):
            ruta = trabajo / "rtc" / f"{item.id}_{pol}.tif"
            ruta.parent.mkdir(parents=True, exist_ok=True)
            alto, ancho = recorte.shape
            perfil = {
                "driver": "GTiff",
                "width": ancho,
                "height": alto,
                "count": 1,
                "dtype": "float32",
                "nodata": float("nan"),
                "crs": str(recorte.crs),
                "transform": recorte.affine,
                "tiled": True,
                "compress": "deflate",
                "BIGTIFF": "IF_SAFER",
            }
            with rasterio.open(ruta, "w", **perfil) as destino:
                for f, c, sub in ventanas:
                    dem = preparar_dem(zona, pais, trabajo / "dem.tif", sub)
                    parcial = trabajo / "parcial.tif"
                    rtc_escena(safe, pol, dem, parcial)
                    with rasterio.open(parcial) as fuente:
                        h, w = fuente.height, fuente.width
                        destino.write(fuente.read(1), 1, window=Window(c, f, w, h))
            rutas[pol] = ruta
        # el SAFE pesa ~1-2 GB: se borra apenas queda el gamma0 recortado
        shutil.rmtree(safe, ignore_errors=True)
        salida.append(EscenaRTC(item, rutas))
        libre_gb = shutil.disk_usage(trabajo).free / 1e9
        alto, ancho = recorte.shape
        avisar(
            f"RTC {item.id} {ancho}x{alto} px en {len(ventanas)} ventanas "
            f"(disco libre {libre_gb:.0f} GB)"
        )
    return salida


def s1_en_grilla(escenas: list[EscenaRTC], geobox: Any) -> xr.Dataset | None:
    """Serie S1 (VV, VH) leída de las escenas corregidas en la ventana de ``geobox``."""
    import rioxarray
    from odc.geo.xr import xr_coords

    coords = xr_coords(geobox)
    tol = abs(geobox.resolution.x) / 2
    capas = []
    for escena in escenas:
        pols = {}
        for pol, ruta in escena.rutas.items():
            leida = rioxarray.open_rasterio(ruta, masked=True)
            assert isinstance(leida, xr.DataArray)
            leida = leida.squeeze("band", drop=True).drop_vars("spatial_ref", errors="ignore")
            pols[pol] = leida.reindex(
                x=coords["x"].values, y=coords["y"].values, method="nearest", tolerance=tol
            )
        capa = xr.Dataset(pols)
        if not bool(capa["VV"].notnull().any()):
            continue  # la escena no toca esta ventana
        capas.append(capa.expand_dims(time=[escena.item.datetime.replace(tzinfo=None)]))
    if not capas:
        return None
    serie = xr.concat(capas, dim="time").load()
    # varias escenas del mismo paso (cortes contiguos de la franja) → una sola fecha
    serie = serie.assign_coords(time=serie["time"].dt.floor("D"))
    return serie.groupby("time").mean(skipna=True)


def cargar_s1_cdse(
    items: list[Any],
    zona: Zona,
    pais: Pais,
    trabajo: Path,
    avisar: Any = print,
    geobox: Any = None,
) -> xr.Dataset | None:
    """Serie S1 (VV, VH, lineal) corregida por relieve, en la grilla nacional."""
    geobox = geobox if geobox is not None else geobox_zona(zona, pais)
    return s1_en_grilla(rtc_escenas(items, zona, pais, trabajo, avisar, geobox), geobox)
