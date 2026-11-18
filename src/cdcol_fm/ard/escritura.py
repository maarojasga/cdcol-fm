"""Escritura del ARD: un COG por banda y mes, y un ítem STAC por mes con su linaje (ADR 0001)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from cdcol_fm import __version__
from cdcol_fm.linaje.hashes import sha256_archivo

PRODUCTO = "ard_s1s2_mensual"
NODATA = {"uint8": 255, "uint16": 0, "float32": np.nan}
# n_validas_s2 y n_adq_s1 usan 255 como sin dato; 0 es un conteo válido
NODATA_BANDA = {"dias_desde_clara": 65535}


def carpeta_producto(destino: Path, zona: str, bloque: str | None = None) -> Path:
    """``<destino>/<zona>/<producto>[/<bloque>]``; dentro, una carpeta por mes."""
    base = destino / zona / PRODUCTO
    return base / bloque if bloque else base


def escribir_mes(
    mes: xr.Dataset,
    destino: Path,
    zona: str,
    ids_fuente: list[str],
    commit: str,
    bloque: str | None = None,
) -> dict[str, Any]:
    """Escribe un mes del ARD y devuelve su ítem STAC (dict)."""
    import rioxarray  # noqa: F401  registra el accesor .rio

    fecha = str(np.datetime_as_string(mes["time"].values, unit="M"))
    carpeta = carpeta_producto(destino, zona, bloque) / fecha
    carpeta.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Any] = {}
    for nombre in mes.data_vars:
        banda = str(nombre)
        capa = mes[banda]
        tipo = "uint16" if banda.startswith("B") else str(capa.dtype)
        nodata = NODATA_BANDA.get(banda, NODATA.get(tipo, np.nan))
        if tipo == "uint16" and banda.startswith("B"):
            capa = capa.fillna(0)
        capa = capa.astype(tipo).rio.write_nodata(nodata)
        ruta = carpeta / f"{banda}.tif"
        capa.rio.to_raster(ruta, driver="COG", compress="DEFLATE")
        assets[banda] = {
            "href": ruta.name,
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "file:checksum": sha256_archivo(ruta),
        }
    oeste, sur, este, norte = mes.rio.transform_bounds("EPSG:4326")
    anillo = [[oeste, sur], [este, sur], [este, norte], [oeste, norte], [oeste, sur]]
    item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": "_".join(p for p in (PRODUCTO, zona, bloque, fecha) if p),
        "bbox": [oeste, sur, este, norte],
        "geometry": {"type": "Polygon", "coordinates": [anillo]},
        "properties": {
            "datetime": f"{fecha}-01T00:00:00Z",
            "proj:code": str(mes.rio.crs),
            "cdcol:producto": PRODUCTO,
            "cdcol:zona": zona,
            "cdcol:bloque": bloque,
            "processing:software": {"cdcol-fm": __version__},
            "cdcol:commit": commit,
            "cdcol:linaje": sorted(ids_fuente),
            "created": datetime.now(UTC).isoformat(),
        },
        "assets": assets,
        "links": [],
    }
    (carpeta / "item.json").write_text(json.dumps(item, indent=2), encoding="utf-8")
    return item
