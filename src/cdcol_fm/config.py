"""Configuración declarativa: países, zonas y recetas.

Lo multipaís se configura, no se programa: un país es un archivo en ``config/paises/``.
Una zona archivada conserva solo su archivo en ``config/zonas/`` y su manifiesto.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

RAIZ_CONFIG = Path(__file__).resolve().parents[2] / "config"


class Grilla(BaseModel):
    crs: str = Field(description="CRS de la grilla nacional, p. ej. EPSG:9377")
    resolucion_m: float = Field(gt=0)
    tesela_px: int = Field(gt=0, description="Lado de la tesela en píxeles")


class Pais(BaseModel):
    id: str
    nombre: str
    grilla: Grilla
    fuentes_etiquetas: list[str] = []


class EstadoZona(StrEnum):
    activa = "activa"
    archivada = "archivada"


class Zona(BaseModel):
    id: str
    pais: str
    descripcion: str
    # [oeste, sur, este, norte] en grados (EPSG:4326)
    bbox: tuple[float, float, float, float]
    fecha_inicio: str
    fecha_fin: str
    estado: EstadoZona = EstadoZona.activa
    conservar_embeddings: bool = False
    productos: list[str] = []

    @model_validator(mode="after")
    def _bbox_valido(self) -> Zona:
        oeste, sur, este, norte = self.bbox
        if not (-180 <= oeste < este <= 180 and -90 <= sur < norte <= 90):
            raise ValueError(f"bbox inválido para la zona {self.id}: {self.bbox}")
        if self.fecha_inicio >= self.fecha_fin:
            raise ValueError(f"fechas invertidas en la zona {self.id}")
        return self


class Receta(BaseModel):
    id: str
    modelo_base: str
    version_base: str
    adaptacion: dict[str, Any] = {}
    semillas: list[int] = [0]


def _leer_yaml(ruta: Path) -> dict[str, Any]:
    with ruta.open(encoding="utf-8") as f:
        datos = yaml.safe_load(f)
    if not isinstance(datos, dict):
        raise ValueError(f"{ruta} no contiene un mapa YAML")
    return datos


def cargar_pais(id_pais: str, raiz: Path = RAIZ_CONFIG) -> Pais:
    return Pais.model_validate(_leer_yaml(raiz / "paises" / f"{id_pais}.yaml"))


def cargar_zona(id_zona: str, raiz: Path = RAIZ_CONFIG) -> Zona:
    return Zona.model_validate(_leer_yaml(raiz / "zonas" / f"{id_zona}.yaml"))


def listar_zonas(raiz: Path = RAIZ_CONFIG) -> list[Zona]:
    return [Zona.model_validate(_leer_yaml(r)) for r in sorted((raiz / "zonas").glob("*.yaml"))]


def cargar_receta(id_receta: str, raiz: Path = RAIZ_CONFIG) -> Receta:
    return Receta.model_validate(_leer_yaml(raiz / "recetas" / f"{id_receta}.yaml"))
