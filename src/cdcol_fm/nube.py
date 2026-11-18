"""Salida a la nube: subir productos a S3 y medir lo que costó producirlos (ADR 0005).

Las credenciales de S3 son las del entorno (en AWS Batch, el rol de la tarea). No se mezclan con
las de CDSE, que solo leen de ``eodata``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


def partir_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/a/b`` → (``bucket``, ``a/b``), sin barra final."""
    if not uri.startswith("s3://"):
        raise ValueError(f"no es una URI de S3: {uri}")
    bucket, _, prefijo = uri[len("s3://") :].partition("/")
    if not bucket:
        raise ValueError(f"falta el bucket en {uri}")
    return bucket, prefijo.strip("/")


def claves(carpeta: Path, prefijo: str) -> list[tuple[Path, str]]:
    """(archivo local, clave en S3) de todo lo que hay bajo ``carpeta``, en orden estable."""
    base = f"{prefijo}/" if prefijo else ""
    return [
        (p, base + p.relative_to(carpeta).as_posix())
        for p in sorted(carpeta.rglob("*"))
        if p.is_file()
    ]


def subir_carpeta(carpeta: Path, uri: str, cliente: Any = None) -> int:
    """Sube ``carpeta`` bajo ``uri`` y devuelve cuántos archivos subió."""
    if cliente is None:
        import boto3  # type: ignore[import-untyped]

        cliente = boto3.client("s3")
    bucket, prefijo = partir_uri(uri)
    pares = claves(carpeta, prefijo)
    for local, clave in pares:
        cliente.upload_file(str(local), bucket, clave)
    return len(pares)


def _memoria_max_mb() -> int | None:
    """Memoria máxima del proceso; None donde no hay ``resource`` (Windows)."""
    try:
        import resource
    except ImportError:
        return None
    # ru_maxrss viene en KiB en Linux, que es donde corre el trabajo
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


class Medicion:
    """Tiempo, memoria máxima y disco de una corrida, para costear (H3) sin leer logs."""

    def __init__(self, carpeta: Path, cada_s: float = 15.0) -> None:
        self.carpeta = carpeta
        self.inicio = time.monotonic()
        self.disco_max = 0
        self._parar = threading.Event()
        # el pico importa más que el final: los .SAFE de S1 se borran al terminar cada escena
        self._hilo = threading.Thread(target=self._muestrear, args=(cada_s,), daemon=True)
        self._hilo.start()

    def _usado(self) -> int:
        return max(shutil.disk_usage(d).used for d in (self.carpeta, tempfile.gettempdir()))

    def _muestrear(self, cada_s: float) -> None:
        while True:
            self.disco_max = max(self.disco_max, self._usado())
            if self._parar.wait(cada_s):
                return

    def resultado(self, **extra: Any) -> dict[str, Any]:
        self._parar.set()
        self._hilo.join()
        self.disco_max = max(self.disco_max, self._usado())
        peso = sum(p.stat().st_size for p in self.carpeta.rglob("*") if p.is_file())
        total = shutil.disk_usage(self.carpeta).total
        return {
            **extra,
            "segundos": round(time.monotonic() - self.inicio),
            "memoria_max_mb": _memoria_max_mb(),
            "productos_mb": round(peso / 2**20, 1),
            "disco_max_gb": round(self.disco_max / 2**30, 1),
            "disco_total_gb": round(total / 2**30, 1),
        }

    def guardar(self, ruta: Path, **extra: Any) -> dict[str, Any]:
        datos = self.resultado(**extra)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
        return datos
