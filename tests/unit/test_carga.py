from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr

from cdcol_fm.ingesta.carga import desfase_dn, quitar_desfase


def _item(offset: float | None, scale: float = 0.0001) -> SimpleNamespace:
    banda = {"scale": scale} if offset is None else {"scale": scale, "offset": offset}
    return SimpleNamespace(assets={"red": SimpleNamespace(extra_fields={"raster:bands": [banda]})})


def test_desfase_de_baseline_nueva() -> None:
    # lo que declara sentinel-2-c1-l2a en Earth Search (baseline 05.10)
    assert desfase_dn([_item(-0.1), _item(-0.1)], "red") == -1000


def test_sin_offset_declarado_es_cero() -> None:
    assert desfase_dn([_item(None)], "red") == 0


def test_desfases_mezclados_fallan() -> None:
    with pytest.raises(ValueError, match="desfases distintos"):
        desfase_dn([_item(-0.1), _item(0.0)], "red")


def test_quitar_desfase_respeta_sin_dato_y_recorta() -> None:
    capa = xr.DataArray(np.array([0, 500, 1000, 1250, 4000], dtype="uint16"))
    salida = quitar_desfase(capa, -1000)
    assert salida.dtype == np.uint16
    # 0 = sin dato; 500 y 1000 quedarían ≤ 0 → 1; bosque (1250) → 250
    assert salida.values.tolist() == [0, 1, 1, 250, 3000]


def test_desfase_cero_no_toca_la_capa() -> None:
    capa = xr.DataArray(np.array([0, 1250], dtype="uint16"))
    assert quitar_desfase(capa, 0) is capa
