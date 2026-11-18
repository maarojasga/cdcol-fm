"""Contrato común para los modelos base (Galileo, TerraMind, ...).

Embeddings de modelos distintos viven en espacios distintos: nunca se mezclan.
"""

from __future__ import annotations

from typing import Any, Protocol


class Encoder(Protocol):
    modelo_base: str
    version: str
    dim: int

    def sha256_pesos(self) -> str: ...

    def embeber(self, serie_ard: Any) -> Any:
        """Serie mensual S1+S2 con capas de incertidumbre (xarray) → embeddings (xarray)."""
        ...


def nombre_producto(modelo_base: str, receta: str, version: str) -> str:
    """Nombre del producto ODC, p. ej. ``emb_galileo-tiny_r1-lora_v1``."""
    for parte in (modelo_base, receta, version):
        if not parte or "_" in parte:
            raise ValueError(f"parte de nombre inválida: {parte!r} (sin '_' ni vacía)")
    return f"emb_{modelo_base}_{receta}_{version}"
