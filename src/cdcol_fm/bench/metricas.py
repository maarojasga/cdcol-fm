"""Métricas por estrato e intervalos por bootstrap pareado."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

Metrica = Callable[[np.ndarray, np.ndarray], float]


def exactitud_balanceada(real: np.ndarray, pred: np.ndarray) -> float:
    """Media de la exhaustividad (recall) de cada clase presente en ``real``."""
    clases = np.unique(real)
    if clases.size == 0:
        return float("nan")
    return float(np.mean([np.mean(pred[real == c] == c) for c in clases]))


def f1_macro(real: np.ndarray, pred: np.ndarray) -> float:
    valores = []
    for c in np.unique(np.concatenate([real, pred])):
        vp = np.sum((pred == c) & (real == c))
        denom = np.sum(pred == c) + np.sum(real == c)
        valores.append(2 * vp / denom if denom else 0.0)
    return float(np.mean(valores)) if valores else float("nan")


METRICAS: dict[str, Metrica] = {
    "exactitud_balanceada": exactitud_balanceada,
    "f1_macro": f1_macro,
}


def brechas_bootstrap(
    real: np.ndarray,
    pred_a: np.ndarray,
    pred_b: np.ndarray,
    estrato: np.ndarray,
    grupos: np.ndarray,
    metrica: Metrica,
    n: int,
    semilla: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Brecha ``metrica(a) − metrica(b)`` por estrato y ``n`` réplicas bootstrap.

    Los dos brazos se miden en los mismos píxeles (pareado). Se remuestrean **grupos** (bloques),
    no píxeles: los píxeles de un bloque no son independientes y remuestrearlos uno a uno daría
    intervalos demasiado angostos. Devuelve (puntual[estratos], réplicas[n, estratos]); los
    estratos son ``0..max(estrato)``.
    """
    n_estratos = int(estrato.max()) + 1
    unicos, codigo = np.unique(grupos, return_inverse=True)
    por_grupo = [np.flatnonzero(codigo == g) for g in range(unicos.size)]

    def brechas(idx: np.ndarray) -> np.ndarray:
        salida = np.full(n_estratos, np.nan)
        for e in range(n_estratos):
            sel = idx[estrato[idx] == e]
            if sel.size:
                salida[e] = metrica(real[sel], pred_a[sel]) - metrica(real[sel], pred_b[sel])
        return salida

    puntual = brechas(np.arange(real.size))
    rng = np.random.default_rng(semilla)
    replicas = np.empty((n, n_estratos))
    for i in range(n):
        elegidos = rng.integers(0, unicos.size, unicos.size)
        replicas[i] = brechas(np.concatenate([por_grupo[g] for g in elegidos]))
    return puntual, replicas


def ic95(replicas: np.ndarray) -> tuple[float, float]:
    finitas = replicas[np.isfinite(replicas)]
    if finitas.size == 0:
        return float("nan"), float("nan")
    bajo, alto = np.quantile(finitas, [0.025, 0.975])
    return float(bajo), float(alto)
