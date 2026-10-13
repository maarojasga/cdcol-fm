"""Descarga de productos Sentinel-1 GRD (SAFE) desde Copernicus Data Space.

Solo se baja lo que la corrección de relieve necesita: manifest, anotaciones,
calibración y las mediciones VV/VH. Las llaves vienen de variables de entorno
(secretos del repositorio), nunca de la config.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

ENDPOINT = "https://eodata.dataspace.copernicus.eu"
BUCKET = "eodata"
VAR_LLAVE = "CDSE_S3_ACCESS_KEY"
VAR_SECRETO = "CDSE_S3_SECRET_KEY"

_PATRON_SAFE = re.compile(r"(?:s3://eodata/|/eodata/)?(?P<prefijo>.+?\.SAFE)(?:/|$)")


def hay_credenciales() -> bool:
    return bool(os.environ.get(VAR_LLAVE) and os.environ.get(VAR_SECRETO))


def prefijo_safe(item: Any) -> str:
    """Ruta del .SAFE dentro del bucket ``eodata``, sacada de los href del ítem."""
    for asset in item.assets.values():
        coincidencia = _PATRON_SAFE.search(asset.href)
        if coincidencia:
            prefijo = coincidencia.group("prefijo")
            return prefijo.removeprefix("eodata/")
    raise ValueError(f"el ítem {item.id} no tiene ningún href dentro de un .SAFE")


def es_iw(item: Any) -> bool:
    modo = item.properties.get("sar:instrument_mode")
    return modo is None or modo == "IW"


def necesario(clave_relativa: str) -> bool:
    """¿Hace falta este archivo del SAFE para la corrección de relieve de VV/VH?"""
    if clave_relativa == "manifest.safe":
        return True
    if clave_relativa.startswith("annotation/") and clave_relativa.endswith(".xml"):
        # anotaciones principales y calibración; el ruido no se usa
        return "/rfi/" not in clave_relativa
    if clave_relativa.startswith("measurement/") and clave_relativa.endswith(".tiff"):
        return "-vv-" in clave_relativa or "-vh-" in clave_relativa
    return False


def descargar_safe(item: Any, destino: Path) -> Path:
    """Baja el .SAFE (solo lo necesario) y devuelve su carpeta local."""
    import boto3  # type: ignore[import-untyped]

    if not hay_credenciales():
        raise RuntimeError(f"faltan {VAR_LLAVE} y {VAR_SECRETO} (llaves S3 de CDSE)")
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=os.environ[VAR_LLAVE],
        aws_secret_access_key=os.environ[VAR_SECRETO],
        region_name="default",
    )
    prefijo = prefijo_safe(item)
    local = destino / Path(prefijo).name
    paginas = s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefijo + "/")
    for pagina in paginas:
        for obj in pagina.get("Contents", []):
            relativa = obj["Key"][len(prefijo) + 1 :]
            if not necesario(relativa):
                continue
            ruta = local / relativa
            if ruta.exists() and ruta.stat().st_size == obj["Size"]:
                continue
            ruta.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(BUCKET, obj["Key"], str(ruta))
    return local
