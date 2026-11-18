import numpy as np
import pytest

from cdcol_fm.bench.metricas import brechas_bootstrap, exactitud_balanceada, f1_macro, ic95


def test_exactitud_balanceada_no_premia_la_clase_mayoritaria() -> None:
    real = np.array([0] * 90 + [1] * 10)
    todo_cero = np.zeros(100, dtype=int)
    assert exactitud_balanceada(real, todo_cero) == pytest.approx(0.5)
    assert exactitud_balanceada(real, real) == 1.0
    assert f1_macro(real, real) == 1.0


def test_brecha_por_estrato_y_ic_por_bloques() -> None:
    rng = np.random.default_rng(0)
    n = 2000
    real = rng.integers(0, 2, n)
    estrato = np.repeat([0, 1], n // 2)
    grupos = np.tile(np.repeat(np.arange(10), n // 20), 2)
    perfecta = real.copy()
    # el brazo a se equivoca en el 30 % del estrato 0 y acierta en el 1
    a = real.copy()
    malos = (estrato == 0) & (rng.random(n) < 0.3)
    a[malos] = 1 - a[malos]
    puntual, replicas = brechas_bootstrap(
        real, a, perfecta, estrato, grupos, exactitud_balanceada, 300
    )
    assert puntual[0] == pytest.approx(-0.3, abs=0.03)
    assert puntual[1] == 0
    bajo, alto = ic95(replicas[:, 0])
    assert bajo < puntual[0] < alto < 0
