"""Qué píxeles entran al experimento: elegibles, estratos, pliegues por bloque y muestras.

Todo trabaja sobre arreglos planos (un elemento por píxel) para no depender de la grilla.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

SIN_CLASE = -1


def reclasificar(
    codigos: np.ndarray,
    tabla: dict[int, int],
    otros_a: int | None = None,
    nodata: int | None = None,
) -> np.ndarray:
    """Códigos de la referencia → clase del experimento (``SIN_CLASE`` si no aplica)."""
    salida = np.full(codigos.shape, SIN_CLASE if otros_a is None else otros_a, dtype="int16")
    for codigo, clase in tabla.items():
        salida[codigos == codigo] = clase
    if nodata is not None:
        salida[codigos == nodata] = SIN_CLASE
    return salida


def homogeneo(clases: np.ndarray, radio: int) -> np.ndarray:
    """True donde la ventana de (2·radio+1)² alrededor del píxel tiene una sola clase válida."""
    if radio == 0:
        return np.asarray(clases != SIN_CLASE)
    lado = 2 * radio + 1
    borde = np.pad(clases, radio, constant_values=SIN_CLASE)
    ventanas = sliding_window_view(borde, (lado, lado))
    centro = clases[..., None, None]
    return np.asarray(np.all(ventanas == centro, axis=(-2, -1)) & (clases != SIN_CLASE))


def estratos_por_cuantiles(valor: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Estrato 0..n-1 por cuantiles de ``valor`` (menor valor → estrato 0) y los cortes.

    Con ``n_validas_anual``, el estrato 0 es el más nublado. NaN → -1.
    """
    finito = np.isfinite(valor)
    cortes = np.quantile(valor[finito], np.linspace(0, 1, n + 1)[1:-1])
    estrato = np.searchsorted(cortes, valor, side="right").astype("int16")
    estrato[~finito] = -1
    return estrato, cortes


def pliegues_por_bloque(bloques: list[str], k: int, semilla: int = 0) -> dict[str, int]:
    """Cada bloque a un pliegue, balanceado y al azar (fijo por semilla)."""
    if len(bloques) < k:
        raise ValueError(f"{len(bloques)} bloques no alcanzan para {k} pliegues")
    orden = np.random.default_rng(semilla).permutation(sorted(bloques))
    return {str(b): i % k for i, b in enumerate(orden)}


def muestrear_por_clase(
    clases: np.ndarray, n_por_clase: int, rng: np.random.Generator, mascara: np.ndarray
) -> np.ndarray:
    """Índices con hasta ``n_por_clase`` píxeles de cada clase dentro de ``mascara``."""
    elegidos = []
    for clase in np.unique(clases[mascara & (clases != SIN_CLASE)]):
        candidatos = np.flatnonzero(mascara & (clases == clase))
        n = min(n_por_clase, candidatos.size)
        elegidos.append(rng.choice(candidatos, size=n, replace=False))
    return np.sort(np.concatenate(elegidos)) if elegidos else np.array([], dtype=int)


def muestra_de_prueba(
    clases: np.ndarray,
    estratos: np.ndarray,
    n_por_clase_y_estrato: int,
    rng: np.random.Generator,
    mascara: np.ndarray,
) -> np.ndarray:
    """Prueba balanceada por clase dentro de cada estrato, para comparar estratos entre sí."""
    partes = [
        muestrear_por_clase(clases, n_por_clase_y_estrato, rng, mascara & (estratos == e))
        for e in np.unique(estratos[mascara & (estratos >= 0)])
    ]
    return np.sort(np.concatenate(partes)) if partes else np.array([], dtype=int)
