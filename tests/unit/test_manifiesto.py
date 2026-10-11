from pathlib import Path

from cdcol_fm.ciclo.manifiesto import ItemFuente, Manifiesto, Producto
from cdcol_fm.linaje.hashes import sha256_archivo, sha256_bytes


def _manifiesto() -> Manifiesto:
    return Manifiesto(
        zona="prueba",
        sha256_config="a" * 64,
        commit_repo="abc123",
        sha256_lockfile="b" * 64,
        items_fuente=[ItemFuente(coleccion="sentinel-2-c1-l2a", id="S2A_x", href="s3://x")],
        pesos={"galileo-tiny": "c" * 64},
        productos=[Producto(nombre="ard_s1s2_mensual", version="v0", sha256="d" * 64)],
    )


def test_ida_y_vuelta(tmp_path: Path) -> None:
    m = _manifiesto()
    ruta = tmp_path / "prueba.json"
    m.guardar(ruta)
    assert Manifiesto.leer(ruta) == m


def test_reconstruccion_identica_no_tiene_diferencias() -> None:
    assert _manifiesto().diferencias(_manifiesto()) == []


def test_detecta_item_faltante_y_pesos_distintos() -> None:
    antes = _manifiesto()
    ahora = _manifiesto()
    ahora.items_fuente = []
    ahora.pesos["galileo-tiny"] = "e" * 64
    difs = antes.diferencias(ahora)
    assert "falta ítem fuente sentinel-2-c1-l2a/S2A_x" in difs
    assert "pesos distintos para galileo-tiny" in difs


def test_sha256_archivo_coincide_con_bytes(tmp_path: Path) -> None:
    ruta = tmp_path / "pesos.bin"
    ruta.write_bytes(b"cdcol" * 1000)
    assert sha256_archivo(ruta) == sha256_bytes(b"cdcol" * 1000)
