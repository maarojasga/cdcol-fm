"""Lógica del compuesto mensual con arreglos sintéticos pequeños (2×2 píxeles)."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from cdcol_fm.ard.bandas import BANDAS_ARD, BANDAS_S2
from cdcol_fm.ard.compuesto import SIN_VISTA_CLARA, compuesto_mensual

VEG, NUBE, SIN_DATO = 4, 9, 0


def _s2(fechas: list[str], scl: list[int], refl: list[float]) -> xr.Dataset:
    """Serie S2 donde todos los píxeles comparten SCL y reflectancia por fecha."""
    t = pd.to_datetime(fechas)
    forma = (len(t), 2, 2)
    coords = {"time": t, "y": [1.0, 0.0], "x": [0.0, 1.0]}
    ds = xr.Dataset(coords=coords)
    for b in BANDAS_S2:
        ds[b] = (("time", "y", "x"), np.broadcast_to(np.array(refl)[:, None, None], forma).copy())
    ds["SCL"] = (("time", "y", "x"), np.broadcast_to(np.array(scl)[:, None, None], forma).copy())
    return ds


def _s1(fechas: list[str], vv: list[float]) -> xr.Dataset:
    t = pd.to_datetime(fechas)
    forma = (len(t), 2, 2)
    datos = np.broadcast_to(np.array(vv)[:, None, None], forma).copy()
    coords = {"time": t, "y": [1.0, 0.0], "x": [0.0, 1.0]}
    return xr.Dataset(
        {"VV": (("time", "y", "x"), datos), "VH": (("time", "y", "x"), datos / 10)}, coords=coords
    )


@pytest.fixture
def ard() -> xr.Dataset:
    # Enero: 3 pasos, 2 válidos (100, 300) y 1 nublado (9999).
    # Febrero: 2 pasos, ambos nublados. Marzo: 1 paso sin dato.
    s2 = _s2(
        ["2024-01-05", "2024-01-10", "2024-01-20", "2024-02-04", "2024-02-14", "2024-03-05"],
        [VEG, VEG, NUBE, NUBE, NUBE, SIN_DATO],
        [100, 300, 9999, 9999, 9999, 0],
    )
    s1 = _s1(["2024-01-07", "2024-01-19", "2024-02-12"], [0.1, 0.1, 0.01])
    return compuesto_mensual(s2, s1)


def _mes(ard: xr.Dataset, banda: str, i: int) -> float:
    return float(ard[banda].isel(time=i, y=0, x=0))


def test_tiene_todas_las_bandas_en_orden(ard: xr.Dataset) -> None:
    assert list(ard.data_vars) == list(BANDAS_ARD)
    assert ard.sizes["time"] == 3


def test_mediana_ignora_la_nube(ard: xr.Dataset) -> None:
    assert _mes(ard, "B04", 0) == 200
    assert np.isnan(_mes(ard, "B04", 1))


def test_cuenta_observaciones_validas(ard: xr.Dataset) -> None:
    assert [_mes(ard, "n_validas_s2", i) for i in range(3)] == [2, 0, 0]


def test_dias_desde_la_ultima_vista_clara(ard: xr.Dataset) -> None:
    # última válida: 10 de enero
    assert _mes(ard, "dias_desde_clara", 0) == 22  # hasta el 1 de febrero
    assert _mes(ard, "dias_desde_clara", 1) == 51  # hasta el 1 de marzo (2024 es bisiesto)
    assert _mes(ard, "dias_desde_clara", 2) == 82  # hasta el 1 de abril


def test_sin_vista_clara_nunca() -> None:
    s2 = _s2(["2024-01-05"], [NUBE], [9999])
    assert int(compuesto_mensual(s2, None)["dias_desde_clara"].max()) == SIN_VISTA_CLARA


def test_vista_clara_fuera_de_la_historia_no_cuenta() -> None:
    # última válida el 10 de enero; en agosto ya pasaron más de HISTORIA_MESES (6) meses
    s2 = _s2(["2024-01-10", "2024-07-05", "2024-08-05"], [VEG, NUBE, NUBE], [100, 9999, 9999])
    ard = compuesto_mensual(s2, None)
    assert _mes(ard, "dias_desde_clara", 6) == 204  # julio: enero está dentro de la ventana
    assert _mes(ard, "dias_desde_clara", 7) == SIN_VISTA_CLARA  # agosto: ya no


def test_un_mes_con_su_historia_da_lo_mismo_que_la_serie_completa(ard: xr.Dataset) -> None:
    """Lo que hace ard-mes: carga la historia y se queda con el último mes."""
    s2 = _s2(
        ["2024-01-05", "2024-01-10", "2024-01-20", "2024-02-04", "2024-02-14", "2024-03-05"],
        [VEG, VEG, NUBE, NUBE, NUBE, SIN_DATO],
        [100, 300, 9999, 9999, 9999, 0],
    )
    solo_marzo = compuesto_mensual(s2, None).sel(time=slice("2024-03-01", None))
    assert solo_marzo.sizes["time"] == 1
    assert _mes(solo_marzo, "dias_desde_clara", 0) == _mes(ard, "dias_desde_clara", 2) == 82


def test_fraccion_de_nube(ard: xr.Dataset) -> None:
    assert _mes(ard, "prob_nube", 0) == 33
    assert _mes(ard, "prob_nube", 1) == 100
    assert _mes(ard, "prob_nube", 2) == 255  # sin observaciones: sin dato


def test_incertidumbre_solo_con_dos_o_mas(ard: xr.Dataset) -> None:
    assert _mes(ard, "incert_s2", 0) == pytest.approx(np.std([100, 300], ddof=1))
    assert np.isnan(_mes(ard, "incert_s2", 1))


def test_radar_en_db_y_conteo(ard: xr.Dataset) -> None:
    assert _mes(ard, "VV", 0) == pytest.approx(-10.0)
    assert _mes(ard, "VV", 1) == pytest.approx(-20.0)
    assert [_mes(ard, "n_adq_s1", i) for i in range(3)] == [2, 1, 0]
    assert np.isnan(_mes(ard, "VV", 2))


def test_sin_radar() -> None:
    s2 = _s2(["2024-01-05"], [VEG], [100])
    ard = compuesto_mensual(s2, None)
    assert int(ard["n_adq_s1"].max()) == 0
    assert bool(ard["VV"].isnull().all())
