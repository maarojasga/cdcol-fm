import pytest
from typer.testing import CliRunner

from cdcol_fm.cli import app
from cdcol_fm.embeddings.interfaz import nombre_producto

runner = CliRunner()


def test_validar_config() -> None:
    r = runner.invoke(app, ["validar-config"])
    assert r.exit_code == 0, r.output
    assert "zonas válidas" in r.output


def test_comandos_pendientes_salen_con_codigo_2() -> None:
    assert runner.invoke(app, ["archivar", "prueba"]).exit_code == 2


def test_nombre_producto_embeddings() -> None:
    assert nombre_producto("galileo-tiny", "r1-lora", "v1") == "emb_galileo-tiny_r1-lora_v1"
    with pytest.raises(ValueError):
        nombre_producto("galileo_tiny", "r1", "v1")
