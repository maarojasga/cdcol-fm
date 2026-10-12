from dataclasses import dataclass, field
from datetime import datetime

import pytest

from cdcol_fm.fuentes.cdse import es_iw, necesario, prefijo_safe

SAFE = "Sentinel-1/SAR/IW_GRDH_1S/2024/01/08/S1A_IW_GRDH_1SDV_20240108T104512_X.SAFE"


@dataclass
class Asset:
    href: str


@dataclass
class Item:
    id: str
    assets: dict[str, Asset]
    properties: dict[str, str] = field(default_factory=dict)
    datetime: datetime = datetime(2024, 1, 8)


def test_prefijo_desde_href_s3() -> None:
    item = Item("x", {"vv": Asset(f"s3://eodata/{SAFE}/measurement/s1a-iw-grd-vv-x.tiff")})
    assert prefijo_safe(item) == SAFE


def test_prefijo_desde_href_del_manifest() -> None:
    item = Item("x", {"safe_manifest": Asset(f"s3://eodata/{SAFE}/manifest.safe")})
    assert prefijo_safe(item) == SAFE


def test_sin_safe_falla() -> None:
    with pytest.raises(ValueError, match="SAFE"):
        prefijo_safe(Item("x", {"thumb": Asset("https://x/preview.png")}))


@pytest.mark.parametrize(
    ("clave", "esperado"),
    [
        ("manifest.safe", True),
        ("annotation/s1a-iw-grd-vv-x.xml", True),
        ("annotation/calibration/calibration-s1a-iw-grd-vv-x.xml", True),
        ("annotation/rfi/rfi-s1a-iw-grd-vv-x.xml", False),
        ("measurement/s1a-iw-grd-vv-x.tiff", True),
        ("measurement/s1a-iw-grd-vh-x.tiff", True),
        ("preview/quick-look.png", False),
        ("support/s1-level-1-product.xsd", False),
    ],
)
def test_solo_baja_lo_necesario(clave: str, esperado: bool) -> None:
    assert necesario(clave) is esperado


def test_filtra_modo_iw() -> None:
    assert es_iw(Item("x", {}, {"sar:instrument_mode": "IW"}))
    assert not es_iw(Item("x", {}, {"sar:instrument_mode": "EW"}))
