import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from cdcol_fm.ard.bandas import BANDAS_ARD
from cdcol_fm.ard.escritura import escribir_mes
from cdcol_fm.linaje.hashes import sha256_archivo


def test_escribe_un_cog_por_banda_y_un_item(tmp_path: Path) -> None:
    import rioxarray  # noqa: F401

    coords = {
        "time": pd.Timestamp("2024-01-01"),
        "y": [1002005.0, 1001995.0],
        "x": [4800005.0, 4800015.0],
    }
    mes = xr.Dataset(coords=coords)
    for b in BANDAS_ARD:
        tipo = (
            "uint8"
            if b in ("n_validas_s2", "prob_nube", "n_adq_s1")
            else ("uint16" if b == "dias_desde_clara" else "float32")
        )
        mes[b] = (("y", "x"), np.ones((2, 2), dtype=tipo))
    mes = mes.rio.write_crs("EPSG:9377")

    item = escribir_mes(mes, tmp_path, "prueba", ["S2A_b", "S2A_a"], "abc")

    carpeta = tmp_path / "prueba" / "ard_s1s2_mensual" / "2024-01"
    assert sorted(item["assets"]) == sorted(BANDAS_ARD)
    assert item["properties"]["cdcol:linaje"] == ["S2A_a", "S2A_b"]
    assert item["properties"]["proj:code"] == "EPSG:9377"
    for banda, asset in item["assets"].items():
        assert asset["file:checksum"] == sha256_archivo(carpeta / f"{banda}.tif")
    assert json.loads((carpeta / "item.json").read_text())["id"] == item["id"]
