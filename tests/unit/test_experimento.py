import pytest

from cdcol_fm.bench.experimento import Experimento, cargar_experimento


def test_e01_trae_alphaearth_externo_y_nube_simulada() -> None:
    exp = cargar_experimento("e01")
    externos = [b.id for b in exp.brazos if b.externo]
    assert externos == ["alphaearth-sonda"]
    assert exp.prueba_nubes is not None
    assert exp.prueba_nubes.nivel == 1
    assert "alphaearth-sonda" not in exp.prueba_nubes.brazos


def _con_prueba(**cambios: object) -> dict:
    datos = cargar_experimento("e01").model_dump()
    datos["prueba_nubes"].update(cambios)
    return datos


def test_prueba_nubes_rechaza_brazo_externo() -> None:
    with pytest.raises(ValueError, match="externo"):
        Experimento.model_validate(_con_prueba(brazos=["local-rf", "alphaearth-sonda"]))


def test_prueba_nubes_rechaza_estrato_inexistente() -> None:
    with pytest.raises(ValueError, match="no es un estrato"):
        Experimento.model_validate(_con_prueba(estrato="soleado"))
