from datetime import datetime
from types import SimpleNamespace

from cdcol_fm.ard.pipeline import _dem_unico, _linaje_mes


def _item(id_: str, fecha: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=id_, datetime=datetime.fromisoformat(fecha) if fecha else None)


def test_linaje_del_mes_trae_historia_s2_y_dem_del_s1() -> None:
    s2 = [
        _item("s2-2023-08", "2023-08-15"),  # fuera de la ventana de 6 meses
        _item("s2-2023-09", "2023-09-15"),
        _item("s2-2024-03", "2024-03-05"),
    ]
    s1 = [_item("s1-2024-02", "2024-02-20"), _item("s1-2024-03", "2024-03-07")]
    dem = {"s1-2024-02": [_item("dem-b")], "s1-2024-03": [_item("dem-a"), _item("dem-b")]}

    ids = _linaje_mes("2024-03", s2, s1, dem)

    assert ids == ["dem-a", "dem-b", "s1-2024-03", "s2-2023-09", "s2-2024-03"]
    assert [t.id for t in _dem_unico(dem)] == ["dem-a", "dem-b"]
