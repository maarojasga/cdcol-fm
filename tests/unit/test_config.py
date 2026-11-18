from pathlib import Path

import pytest
import yaml

from cdcol_fm.ard.bandas import BANDAS_ARD, BANDAS_INCERTIDUMBRE
from cdcol_fm.config import RAIZ_CONFIG, Zona, cargar_pais, cargar_receta, listar_zonas


def test_todas_las_zonas_son_validas() -> None:
    zonas = listar_zonas()
    assert {z.id for z in zonas} >= {"prueba", "macarena", "eje-cafetero", "meta-arroz", "choco"}
    for z in zonas:
        assert cargar_pais(z.pais).grilla.crs == "EPSG:9377"


def test_bbox_invertido_falla() -> None:
    with pytest.raises(ValueError, match="bbox"):
        Zona(
            id="x",
            pais="colombia",
            descripcion="",
            bbox=(-75.0, 5.0, -76.0, 6.0),
            fecha_inicio="2024-01-01",
            fecha_fin="2024-02-01",
        )


def test_receta_base() -> None:
    assert cargar_receta("r0-base").modelo_base == "galileo-tiny"


def test_producto_ard_tiene_todas_las_bandas() -> None:
    ruta: Path = RAIZ_CONFIG / "productos" / "ard_s1s2_mensual.yaml"
    producto = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    nombres = [m["name"] for m in producto["measurements"]]
    assert nombres == list(BANDAS_ARD)
    assert set(BANDAS_INCERTIDUMBRE) <= set(nombres)


def test_cargar_env_tolera_windows_y_no_pisa_el_entorno(tmp_path, monkeypatch) -> None:
    import os

    from cdcol_fm.config import cargar_env

    ruta = tmp_path / ".env"
    ruta.write_bytes(
        "\ufeff# comentario\r\nA_LLAVE=abc\r\nB_LLAVE=\"con comillas\"\r\n"
        "export C_LLAVE='x=y'\r\nVACIA=\r\nYA_ESTA=del_archivo\r\n".encode()
    )
    for n in ("A_LLAVE", "B_LLAVE", "C_LLAVE", "VACIA"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("YA_ESTA", "del_entorno")
    cargar_env(ruta)
    assert os.environ["A_LLAVE"] == "abc"
    assert os.environ["B_LLAVE"] == "con comillas"
    assert os.environ["C_LLAVE"] == "x=y"
    assert "VACIA" not in os.environ
    assert os.environ["YA_ESTA"] == "del_entorno"
    cargar_env(tmp_path / "no-existe")  # sin .env no pasa nada
