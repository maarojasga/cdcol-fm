import pytest

from cdcol_fm.ard.bloques import bloques_de_zona
from cdcol_fm.bench.seleccion import REDUCCION, Candidato, anio_item, elegir
from cdcol_fm.config import cargar_pais, cargar_zona


def _candidatos() -> list[Candidato]:
    salida = []
    for fila in range(10):
        for col in range(4):
            bosque = [0.05, 0.3, 0.6, 0.95][col]  # solo las columnas 1 y 2 son mixtas
            dentro = 0.5 if fila == 9 else 1.0  # la fila de arriba queda en el borde
            salida.append(Candidato(f"x{col}_y{fila}", col, fila, dentro, bosque))
    return salida


def test_solo_mixtos_y_enteros_repartidos_de_sur_a_norte() -> None:
    elegidos = elegir(_candidatos(), franjas=3, por_franja=2, semilla=0)
    assert len(elegidos) == 6
    assert all(c.columna in (1, 2) and c.fila < 9 for c in elegidos)
    # 18 elegibles en 3 franjas de 6 (filas 0-2, 3-5, 6-8): dos por franja
    assert sorted(c.fila // 3 for c in elegidos) == [0, 0, 1, 1, 2, 2]


def test_misma_semilla_misma_seleccion() -> None:
    a = elegir(_candidatos(), 3, 2, semilla=7)
    assert a == elegir(list(reversed(_candidatos())), 3, 2, semilla=7)


def test_faltan_elegibles() -> None:
    with pytest.raises(ValueError, match="elegibles"):
        elegir(_candidatos(), franjas=5, por_franja=4)


def test_grilla_resumida_del_bloque() -> None:
    pais = cargar_pais("colombia")
    b = bloques_de_zona(cargar_zona("macarena"), pais)[0]
    gb = b.geobox().zoom_out(REDUCCION)
    assert gb.shape == (1024 // REDUCCION, 1024 // REDUCCION)
    assert gb.extent.boundingbox.left == pytest.approx(b.limites[0])


def test_anio_de_items_con_rango_de_fechas() -> None:
    """Como WorldCover: datetime nulo y start_datetime/end_datetime."""
    from datetime import UTC, datetime

    import pystac

    def item(anio: int) -> pystac.Item:
        return pystac.Item(
            id=f"ESA_WorldCover_10m_{anio}",
            geometry=None,
            bbox=None,
            datetime=None,
            properties={},
            start_datetime=datetime(anio, 1, 1, tzinfo=UTC),
            end_datetime=datetime(anio, 12, 31, tzinfo=UTC),
        )

    assert [anio_item(item(a)) for a in (2020, 2021)] == [2020, 2021]
