"""Hashes estables para pesos, productos y recetas."""

from __future__ import annotations

import hashlib
from pathlib import Path

_BLOQUE = 1 << 20


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while bloque := f.read(_BLOQUE):
            h.update(bloque)
    return h.hexdigest()


def sha256_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()
