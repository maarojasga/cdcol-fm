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


def test_recorte_en_multiplos_de_trozo() -> None:
    from cdcol_fm.ard.rtc import TROZO, _recorte

    pais = cargar_pais("colombia")
    gb = geobox_zona(cargar_zona("macarena"), pais)
    # una escena que cubre toda la zona
    b = gb.geographic_extent.boundingbox
    anillo = [[b.left, b.bottom], [b.right, b.bottom], [b.right, b.top], [b.left, b.top]]
    item = SimpleNamespace(geometry={"type": "Polygon", "coordinates": [anillo + [anillo[0]]]})
    r = _recorte(item, gb, pais)
    assert r is not None
    recorte, _ = r
    assert all(n % TROZO == 0 for n in recorte.shape)
    assert recorte.affine.c == pytest.approx(gb.affine.c, abs=10)


def test_ventanas_cubren_el_recorte() -> None:
    from odc.geo.geom import box

    from cdcol_fm.ard.rtc import VENTANA, _ventanas

    recorte = GeoBox((3 * 1024, 5 * 1024), Affine(10, 0, 0, 0, -10, 100000), CRS)
    ventanas = _ventanas(recorte, recorte.extent)
    assert len(ventanas) == 2 * 3  # 3072/2048 → 2 filas, 5120/2048 → 3 columnas
    assert sum(sub.shape[0] * sub.shape[1] for _, _, sub in ventanas) == 3 * 5 * 1024**2
    assert all(n % 1024 == 0 for _, _, sub in ventanas for n in sub.shape)
    assert ventanas[1][:2] == (0, VENTANA)
    # una huella que solo toca la esquina superior izquierda
    esquina = box(0, 100000 - 5000, 5000, 100000, CRS)
    assert [(f, c) for f, c, _ in _ventanas(recorte, esquina)] == [(0, 0)]


def test_correr_aparte_usa_un_proceso_nuevo_por_tarea(tmp_path: Path) -> None:
    import shutil

    from cdcol_fm.ard.rtc import correr_aparte, pool_aparte

    origen = tmp_path / "a.txt"
    origen.write_text("hola")
    pool = pool_aparte()
    try:
        correr_aparte(pool, shutil.copyfile, origen, tmp_path / "b.txt")
        correr_aparte(pool, shutil.copyfile, origen, tmp_path / "c.txt")
        with pytest.raises(FileNotFoundError):
            correr_aparte(pool, shutil.copyfile, tmp_path / "no-existe", tmp_path / "d.txt")
    finally:
        pool.shutdown()
    assert (tmp_path / "b.txt").read_text() == (tmp_path / "c.txt").read_text() == "hola"
