"""Los brazos del experimento: lo que se ajusta con pocas etiquetas y se compara."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class Clasificador(Protocol):
    def fit(self, x: np.ndarray, y: np.ndarray) -> Any: ...

    def predict(self, x: np.ndarray) -> np.ndarray: ...


def _imputar(x: np.ndarray, medias: np.ndarray) -> np.ndarray:
    return np.where(np.isnan(x), medias, x)


class ConImputacion:
    """Rellena NaN (meses o rasgos sin dato) con la media de entrenamiento antes de ajustar."""

    def __init__(self, base: Clasificador) -> None:
        self.base = base
        self.medias: np.ndarray | None = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> ConImputacion:
        medias = np.nanmean(np.where(np.isfinite(x), x, np.nan), axis=0)
        self.medias = np.nan_to_num(medias)
        self.base.fit(_imputar(x, self.medias), y)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        assert self.medias is not None, "fit antes de predict"
        return np.asarray(self.base.predict(_imputar(x, self.medias)))


def crear(tipo: str, semilla: int) -> Clasificador:
    """Clasificador de un brazo. Sin ajuste de hiperparámetros: los mismos para todos."""
    if tipo == "bosque-aleatorio":
        from sklearn.ensemble import RandomForestClassifier  # type: ignore[import-untyped]

        base: Any = RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=semilla)
    elif tipo == "sonda-lineal":
        from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
        from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
        from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

        base = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    else:
        raise ValueError(f"tipo de brazo desconocido: {tipo}")
    return ConImputacion(base)
