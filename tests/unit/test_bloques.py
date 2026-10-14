import pytest

from cdcol_fm.ard.bloques import bloque, bloques_de_zona, recortar_zona
from cdcol_fm.config import cargar_pais, cargar_zona

PAIS = cargar_pais("colombia")


def test_bloque_alineado_a_la_grilla_nacional() -> None:
    b = bloque("x476_y175", PAIS)
    gb = b.geobox()
    assert gb.shape == (1024, 1024)
    assert gb.crs == "EPSG:9377"
    x0, y0, x1, y1 = b.limites
    assert (x0, y0) == (476 * 10240, 175 * 10240)
    assert gb.extent.boundingbox.left == pytest.approx(x0)
    assert gb.extent.boundingbox.top == pytest.approx(y1)


def test_id_invalido() -> None:
    with pytest.raises(ValueError):
        bloque("476_175", PAIS)


def test_bloques_cubren_la_zona_sin_repetir() -> None:
    zona = cargar_zona("macarena")
    lista = bloques_de_zona(zona, PAIS)
    ids = [b.id for b in lista]
    assert len(ids) == len(set(ids)) > 50
    # la zona de prueba (~2 km) cae en unos pocos bloques
    assert 1 <= len(bloques_de_zona(cargar_zona("prueba"), PAIS)) <= 4


def test_recortar_zona_por_bloque_y_meses() -> None:
    zona = cargar_zona("macarena")
    b = bloques_de_zona(zona, PAIS)[0]
    sub = recortar_zona(zona, b, "2024-02", "2024-02")
    assert (sub.fecha_inicio, sub.fecha_fin) == ("2024-02-01", "2024-02-29")
    oeste, sur, este, norte = sub.bbox
    assert este - oeste < 0.2 and norte - sur < 0.2
    # sin argumentos no cambia nada
    assert recortar_zona(zona) == zona
