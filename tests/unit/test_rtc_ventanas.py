from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from affine import Affine
from odc.geo.geobox import GeoBox

from cdcol_fm.ard.rtc import EscenaRTC, geobox_zona, s1_en_grilla
from cdcol_fm.config import cargar_pais, cargar_zona

CRS = "EPSG:9377"


def _raster(ruta: Path, gb: GeoBox, valor: float) -> Path:
    import rioxarray  # noqa: F401
    from odc.geo.xr import xr_coords

    c = xr_coords(gb)
    da = xr.DataArray(
        np.full(gb.shape, valor, dtype="float32"),
        dims=("y", "x"),
        coords={"y": c["y"], "x": c["x"]},
    ).rio.write_crs(CRS)
    da.rio.to_raster(ruta)
    return ruta


def _escena(tmp: Path, nombre: str, gb: GeoBox, valor: float, hora: int) -> EscenaRTC:
    item = SimpleNamespace(id=nombre, datetime=datetime(2024, 1, 8, hora, tzinfo=UTC))
    rutas = {p: _raster(tmp / f"{nombre}_{p}.tif", gb, valor) for p in ("VV", "VH")}
    return EscenaRTC(item, rutas)


def test_ventana_de_bloque_y_union_del_mismo_dia(tmp_path: Path) -> None:
    # dos cortes contiguos del mismo paso: norte (valor 1) y sur (valor 3), 4x4 px cada uno
    norte = GeoBox((4, 4), Affine(10, 0, 1000, 0, -10, 1080), CRS)
    sur = GeoBox((4, 4), Affine(10, 0, 1000, 0, -10, 1040), CRS)
    escenas = [_escena(tmp_path, "a", norte, 1.0, 10), _escena(tmp_path, "b", sur, 3.0, 11)]
    # ventana de 4x4 que cruza el borde entre los dos cortes
    ventana = GeoBox((4, 4), Affine(10, 0, 1000, 0, -10, 1060), CRS)
    s1 = s1_en_grilla(escenas, ventana)
    assert s1 is not None
    assert s1.sizes["time"] == 1  # mismo día → una sola fecha
    vv = s1["VV"].isel(time=0).values
    np.testing.assert_allclose(vv[:2], 1.0)
    np.testing.assert_allclose(vv[2:], 3.0)


def test_escena_fuera_de_la_ventana(tmp_path: Path) -> None:
    lejos = GeoBox((4, 4), Affine(10, 0, 9000, 0, -10, 9000), CRS)
    ventana = GeoBox((4, 4), Affine(10, 0, 1000, 0, -10, 1040), CRS)
    assert s1_en_grilla([_escena(tmp_path, "c", lejos, 1.0, 10)], ventana) is None


def test_geobox_zona_alineado_a_la_resolucion() -> None:
    pais = cargar_pais("colombia")
    gb = geobox_zona(cargar_zona("prueba"), pais)
    x0, y1 = gb.affine.c, gb.affine.f
    assert x0 % 10 == pytest.approx(0) and y1 % 10 == pytest.approx(0)
