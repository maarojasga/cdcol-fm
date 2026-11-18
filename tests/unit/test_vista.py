import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from cdcol_fm.ard.bandas import BANDAS_ARD
from cdcol_fm.ard.escritura import escribir_mes
from cdcol_fm.ard.vista import CAPAS, generar_vista


def _mes(fecha: str, x0: float, y1: float, n: int = 8) -> xr.Dataset:
    import rioxarray  # noqa: F401

    coords = {
        "time": pd.Timestamp(fecha),
        "y": y1 - 5 - 10 * np.arange(n),
        "x": x0 + 5 + 10 * np.arange(n),
    }
    mes = xr.Dataset(coords=coords)
    rng = np.random.default_rng(0)
    for b in BANDAS_ARD:
        if b in ("n_validas_s2", "prob_nube", "n_adq_s1"):
            datos = rng.integers(0, 6, (n, n)).astype("uint8")
        elif b == "dias_desde_clara":
            datos = rng.integers(0, 60, (n, n)).astype("uint16")
        elif b in ("VV", "VH"):
            datos = rng.uniform(-25, 0, (n, n)).astype("float32")
        else:
            datos = rng.uniform(0, 3000, (n, n)).astype("float32")
        mes[b] = (("y", "x"), datos)
    return mes.rio.write_crs("EPSG:9377")


def test_vista_de_zona_sin_bloques(tmp_path: Path) -> None:
    escribir_mes(_mes("2024-01-01", 4800000, 1002000), tmp_path, "prueba", ["a"], "abc")
    escribir_mes(_mes("2024-02-01", 4800000, 1002000), tmp_path, "prueba", ["a"], "abc")
    ruta = generar_vista(tmp_path, "prueba")
    datos = json.loads(ruta.read_text().split("const D = ")[1].split(";\n")[0])
    assert datos["meses"] == ["2024-01", "2024-02"]
    for capa in CAPAS:
        assert (ruta.parent / "2024-02" / f"{capa.id}.png").stat().st_size > 0


def test_vista_pega_los_bloques_en_un_mosaico(tmp_path: Path) -> None:
    import rasterio

    lado = 10240.0
    for col, fila in ((476, 175), (477, 175), (476, 176)):
        mes = _mes("2024-01-01", col * lado, (fila + 1) * lado)
        escribir_mes(mes, tmp_path, "macarena", ["a"], "abc", f"x{col}_y{fila}")
    ruta = generar_vista(tmp_path, "macarena", lado_bloque=8)
    with rasterio.open(ruta.parent / "2024-01" / "color.png") as img:
        assert (img.width, img.height) == (16, 16)  # 2 columnas × 2 filas de 8 px
        rgb = img.read()
    # el bloque que falta (x477_y176, arriba a la derecha) queda negro
    assert rgb[:, :8, 8:].max() == 0
    assert rgb[:, 8:, :8].max() > 0


def test_vista_sin_productos(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        generar_vista(tmp_path, "nada")
