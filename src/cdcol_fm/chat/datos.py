"""El ARD ya calculado, visto desde el chat: qué hay, leerlo y resumirlo.

La raíz es la misma carpeta que escribe ``cdcol ard-mes``: local (``data``) o
``s3://<bucket>/zonas`` (ADR 0005). Las credenciales de S3 son las del entorno.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

PRODUCTO = "ard_s1s2_mensual"
_MES = re.compile(r"^\d{4}-\d{2}$")
_BLOQUE = re.compile(r"^x(-?\d+)_y(-?\d+)$")


class Almacen:
    """Zonas, bloques y meses calculados bajo una raíz local o de S3."""

    def __init__(self, raiz: str | Path) -> None:
        self.raiz = str(raiz).replace("\\", "/").rstrip("/")
        self.s3 = self.raiz.startswith("s3://")

    def _listar(self, prefijo: str) -> list[str]:
        """Nombres de las subcarpetas inmediatas de ``<raiz>/<prefijo>``."""
        if not self.s3:
            base = Path(self.raiz, prefijo)
            return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        import boto3  # type: ignore[import-untyped]

        from cdcol_fm.nube import partir_uri

        bucket, raiz = partir_uri(self.raiz)
        completo = "/".join(p for p in (raiz, prefijo.strip("/")) if p) + "/"
        nombres = []
        paginas = boto3.client("s3").get_paginator("list_objects_v2")
        for pagina in paginas.paginate(Bucket=bucket, Prefix=completo, Delimiter="/"):
            prefijos = pagina.get("CommonPrefixes", [])
            nombres += [c["Prefix"][len(completo) :].rstrip("/") for c in prefijos]
        return sorted(nombres)

    def zonas(self) -> list[str]:
        return [z for z in self._listar("") if self.bloques(z)]

    def bloques(self, zona: str) -> list[str]:
        return [b for b in self._listar(f"{zona}/{PRODUCTO}") if _BLOQUE.match(b)]

    def meses(self, zona: str, bloque: str) -> list[str]:
        return [m for m in self._listar(f"{zona}/{PRODUCTO}/{bloque}") if _MES.match(m)]

    def ruta(self, zona: str, bloque: str, mes: str, banda: str) -> str:
        return f"{self.raiz}/{zona}/{PRODUCTO}/{bloque}/{mes}/{banda}.tif"


@lru_cache(maxsize=96)
def leer(ruta: str, lado: int | None = None) -> np.ndarray:
    """Banda como float32 con NaN donde no hay dato; ``lado`` reduce con las vistas del COG."""
    import rasterio  # type: ignore[import-untyped]

    with rasterio.open(ruta) as f:
        forma = (lado, lado) if lado else (f.height, f.width)
        datos = f.read(1, out_shape=forma, masked=True).astype("float32")
    salida = np.ma.filled(datos, np.nan)
    salida.flags.writeable = False  # va a una caché compartida
    return salida


def _indice(a: str, b: str) -> Callable[[dict[str, np.ndarray]], np.ndarray]:
    def calcular(x: dict[str, np.ndarray]) -> np.ndarray:
        suma = x[a] + x[b]
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(suma > 0, (x[a] - x[b]) / suma, np.nan)

    return calcular


def _reflectancia(banda: str) -> Callable[[dict[str, np.ndarray]], np.ndarray]:
    return lambda x: x[banda] / 10_000


@dataclass(frozen=True)
class Variable:
    nombre: str
    descripcion: str
    unidad: str
    bandas: tuple[str, ...]
    calcular: Callable[[dict[str, np.ndarray]], np.ndarray]
    rango: tuple[float, float]  # para pintarla


def _directa(banda: str) -> Callable[[dict[str, np.ndarray]], np.ndarray]:
    return lambda x: x[banda]


_LISTA = [
    Variable("ndvi", "Índice de vegetación (B08, B04): más alto = más vegetación verde", "",
             ("B08", "B04"), _indice("B08", "B04"), (0.0, 1.0)),
    Variable("ndmi", "Humedad de la vegetación (B08, B11)", "", ("B08", "B11"),
             _indice("B08", "B11"), (-0.4, 0.6)),
    Variable("ndwi", "Agua en superficie (B03, B08): positivo suele ser agua", "", ("B03", "B08"),
             _indice("B03", "B08"), (-0.6, 0.4)),
    Variable("vv", "Radar Sentinel-1 VV corregido por relieve (gamma0)", "dB", ("VV",),
             _directa("VV"), (-20.0, 0.0)),
    Variable("vh", "Radar Sentinel-1 VH, sensible a la vegetación", "dB", ("VH",),
             _directa("VH"), (-28.0, -8.0)),
    Variable("vh_vv", "Razón VH/VV del radar (VH − VV en dB)", "dB", ("VH", "VV"),
             lambda x: x["VH"] - x["VV"], (-12.0, -3.0)),
    Variable("n_validas_s2", "Observaciones ópticas sin nube en el mes", "fechas",
             ("n_validas_s2",), _directa("n_validas_s2"), (0.0, 6.0)),
    Variable("prob_nube", "Porcentaje de observaciones con nube o sombra", "%",
             ("prob_nube",), _directa("prob_nube"), (0.0, 100.0)),
    Variable("dias_desde_clara", "Días desde la última vista óptica limpia", "días",
             ("dias_desde_clara",), _directa("dias_desde_clara"), (0.0, 60.0)),
    Variable("incert_s2", "Dispersión entre observaciones ópticas del mes (incertidumbre)", "",
             ("incert_s2",), _directa("incert_s2"), (0.0, 500.0)),
    Variable("n_adq_s1", "Adquisiciones de radar en el mes", "fechas", ("n_adq_s1",),
             _directa("n_adq_s1"), (0.0, 6.0)),
] + [
    Variable(b.lower(), f"Reflectancia de Sentinel-2 {b}", "reflectancia (0-1)", (b,),
             _reflectancia(b), (0.0, 0.5))
    for b in ("B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12")
]
VARIABLES = {v.nombre: v for v in _LISTA}


def valores(
    almacen: Almacen, zona: str, bloque: str, mes: str, variable: str, lado: int | None = None
) -> np.ndarray:
    v = VARIABLES[variable]
    bandas = {b: leer(almacen.ruta(zona, bloque, mes, b), lado) for b in v.bandas}
    return np.asarray(v.calcular(bandas), dtype="float32")


def resumir(x: np.ndarray) -> dict[str, float | int | None]:
    """Media y percentiles de lo que tiene dato, y qué fracción tiene dato."""
    finito = x[np.isfinite(x)]
    if finito.size == 0:
        return {"pixeles": int(x.size), "con_dato_pct": 0.0, "media": None,
                "p10": None, "p50": None, "p90": None}
    p10, p50, p90 = np.percentile(finito, [10, 50, 90])
    return {
        "pixeles": int(x.size),
        "con_dato_pct": round(100 * finito.size / x.size, 1),
        "media": _redondo(finito.mean()),
        "p10": _redondo(p10),
        "p50": _redondo(p50),
        "p90": _redondo(p90),
    }


def _redondo(v: float) -> float:
    return float(f"{float(v):.4g}")
