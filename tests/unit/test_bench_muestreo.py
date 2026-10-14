import numpy as np
import pytest

from cdcol_fm.bench.muestreo import (
    SIN_CLASE,
    estratos_por_cuantiles,
    homogeneo,
    muestra_de_prueba,
    muestrear_por_clase,
    pliegues_por_bloque,
    reclasificar,
)


def test_reclasificar_con_otros_y_nodata() -> None:
    codigos = np.array([3, 4, 15, 0, 33])
    assert reclasificar(codigos, {3: 1, 4: 1}, otros_a=0, nodata=0).tolist() == [1, 1, 0, -1, 0]
    assert reclasificar(codigos, {3: 1}).tolist() == [1, -1, -1, -1, -1]


def test_homogeneo_descarta_bordes_de_clase_y_de_imagen() -> None:
    clases = np.zeros((5, 6), dtype="int16")
    clases[:, 3:] = 1
    ok = homogeneo(clases, 1)
    assert not ok[0].any() and not ok[-1].any()  # borde de la imagen
    assert ok[2].tolist() == [False, True, False, False, True, False]
    assert homogeneo(clases, 0).all()


def test_estratos_por_terciles() -> None:
    valor = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, np.nan])
    estrato, cortes = estratos_por_cuantiles(valor, 3)
    assert cortes.size == 2
    assert estrato.tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 2, -1]


def test_pliegues_balanceados_y_fijos() -> None:
    bloques = [f"x{i}_y0" for i in range(10)]
    p = pliegues_por_bloque(bloques, 5, semilla=3)
    assert sorted(np.bincount(list(p.values()))) == [2] * 5
    assert p == pliegues_por_bloque(list(reversed(bloques)), 5, semilla=3)
    with pytest.raises(ValueError):
        pliegues_por_bloque(bloques[:3], 5)


def test_muestras_balanceadas_por_clase_y_estrato() -> None:
    rng = np.random.default_rng(0)
    clases = np.array([0] * 50 + [1] * 10 + [SIN_CLASE] * 5)
    idx = muestrear_por_clase(clases, 20, rng, np.ones(clases.size, bool))
    assert np.bincount(clases[idx]).tolist() == [20, 10]
    estratos = np.arange(clases.size) % 2
    prueba = muestra_de_prueba(clases, estratos, 3, rng, np.ones(clases.size, bool))
    for e in (0, 1):
        assert np.bincount(clases[prueba][estratos[prueba] == e]).tolist() == [3, 3]
