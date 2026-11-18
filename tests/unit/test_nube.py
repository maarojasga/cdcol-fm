import json
from pathlib import Path

import pytest

from cdcol_fm.nube import Medicion, claves, partir_uri, subir_carpeta


def test_partir_uri() -> None:
    assert partir_uri("s3://cubo/zonas/") == ("cubo", "zonas")
    assert partir_uri("s3://cubo") == ("cubo", "")
    with pytest.raises(ValueError):
        partir_uri("/datos/zonas")
    with pytest.raises(ValueError):
        partir_uri("s3:///zonas")


def _arbol(raiz: Path) -> Path:
    zona = raiz / "macarena"
    (zona / "ard_s1s2_mensual" / "x479_y182" / "2024-01").mkdir(parents=True)
    (zona / "ard_s1s2_mensual" / "x479_y182" / "2024-01" / "B04.tif").write_bytes(b"0" * 10)
    (zona / "manifiesto_x479_y182_2024-01.json").write_text("{}")
    return zona


def test_claves_respetan_la_estructura(tmp_path: Path) -> None:
    zona = _arbol(tmp_path)
    assert [c for _, c in claves(zona, "zonas/macarena")] == [
        "zonas/macarena/ard_s1s2_mensual/x479_y182/2024-01/B04.tif",
        "zonas/macarena/manifiesto_x479_y182_2024-01.json",
    ]


def test_subir_carpeta_usa_el_cliente(tmp_path: Path) -> None:
    zona = _arbol(tmp_path)
    subidas: list[tuple[str, str]] = []

    class Falso:
        def upload_file(self, local: str, bucket: str, clave: str) -> None:
            assert Path(local).is_file()
            subidas.append((bucket, clave))

    assert subir_carpeta(zona, "s3://cubo/zonas/macarena", Falso()) == 2
    assert all(b == "cubo" for b, _ in subidas)


def test_medicion_guarda_tiempo_y_disco(tmp_path: Path) -> None:
    zona = _arbol(tmp_path)
    datos = Medicion(tmp_path, cada_s=0.01).guardar(zona / "mediciones" / "2024-01.json", mes="2024-01")
    leido = json.loads((zona / "mediciones" / "2024-01.json").read_text())
    assert leido == datos
    assert datos["mes"] == "2024-01"
    assert datos["disco_max_gb"] > 0
    assert datos["productos_mb"] >= 0
