"""De la config de una zona al producto ``ard_s1s2_mensual`` escrito en disco, con su manifiesto."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cdcol_fm.ard.bloques import bloque as cargar_bloque
from cdcol_fm.ard.bloques import recortar_zona
from cdcol_fm.ard.compuesto import compuesto_mensual
from cdcol_fm.ard.escritura import carpeta_producto, escribir_mes
from cdcol_fm.ciclo.manifiesto import ItemFuente, Manifiesto, Producto
from cdcol_fm.config import RAIZ_CONFIG, cargar_pais, cargar_zona
from cdcol_fm.fuentes.stac import S1_GRD_CDSE, S1_RTC, S2_L2A, buscar
from cdcol_fm.ingesta.carga import cargar_s1, cargar_s2
from cdcol_fm.linaje.hashes import sha256_archivo, sha256_bytes

if TYPE_CHECKING:
    from cdcol_fm.ard.rtc import EscenaRTC

RAIZ_REPO = RAIZ_CONFIG.parent


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=RAIZ_REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"


def _dias(serie: Any) -> set[Any]:
    return {t.date() for t in serie.indexes["time"]}


def _mes(item: Any) -> str:
    return str(item.datetime.strftime("%Y-%m"))


def construir_ard(
    id_zona: str,
    destino: Path,
    avisar: Callable[[str], None] = print,
    fuente_s1: str = "pc",
    id_bloque: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    escenas_s1: list[EscenaRTC] | None = None,
) -> Manifiesto:
    """``fuente_s1``: ``pc`` (RTC de Planetary Computer) o ``cdse`` (GRD + RTC propio).

    Con ``id_bloque`` se calcula solo ese bloque de la grilla nacional; con ``desde`` y
    ``hasta`` (``AAAA-MM``), solo esos meses. Así una zona grande se parte en trabajos chicos.
    """
    zona_completa = cargar_zona(id_zona)
    pais = cargar_pais(zona_completa.pais)
    bloque_ = cargar_bloque(id_bloque, pais) if id_bloque else None
    geobox = bloque_.geobox() if bloque_ else None
    zona = recortar_zona(zona_completa, bloque_, desde, hasta)

    items_s2 = buscar(S2_L2A, zona)
    avisar(f"S2: {len(items_s2)} escenas")
    if not items_s2:
        raise RuntimeError(f"no hay escenas S2 para {id_zona}")
    s2 = cargar_s2(items_s2, zona, pais, geobox)
    if fuente_s1 == "cdse":
        from cdcol_fm.ard.rtc import rtc_escenas, s1_en_grilla
        from cdcol_fm.fuentes.cdse import es_iw

        trabajo = destino / id_zona / f"_trabajo_{id_bloque or 'zona'}"
        if escenas_s1 is None:
            items_s1 = [it for it in buscar(S1_GRD_CDSE, zona) if es_iw(it)]
            avisar(f"S1 (CDSE GRD): {len(items_s1)} escenas")
            escenas = rtc_escenas(items_s1, zona, pais, trabajo, avisar, geobox)
        else:
            # ya corregidas para toda la zona (construir_ard_mes): solo se lee la ventana
            escenas = escenas_s1
        s1 = s1_en_grilla(escenas, s2.odc.geobox) if escenas else None
        if s1 is not None:
            items_s1 = [e.item for e in escenas if e.item.datetime.date() in _dias(s1)]
            # misma grilla que S2 por construcción; esto solo absorbe redondeos de coordenadas
            tol = pais.grilla.resolucion_m / 2
            s1 = s1.reindex(x=s2["x"], y=s2["y"], method="nearest", tolerance=tol)
        else:
            items_s1 = []
        if escenas_s1 is None:
            shutil.rmtree(trabajo, ignore_errors=True)
    elif fuente_s1 == "pc":
        items_s1 = buscar(S1_RTC, zona)
        avisar(f"S1 (PC RTC): {len(items_s1)} escenas")
        s1 = cargar_s1(items_s1, zona, pais, geobox) if items_s1 else None
    else:
        raise ValueError(f"fuente_s1 desconocida: {fuente_s1}")
    ard = compuesto_mensual(s2, s1).compute()

    commit = _commit()
    productos = []
    for i in range(ard.sizes["time"]):
        mes = ard.isel(time=i)
        clave = str(mes["time"].values)[:7]
        ids = [it.id for it in items_s2 + items_s1 if _mes(it) == clave]
        item = escribir_mes(mes, destino, id_zona, ids, commit, id_bloque)
        ruta_item = carpeta_producto(destino, id_zona, id_bloque) / clave / "item.json"
        productos.append(
            Producto(nombre=item["id"], version="v0", sha256=sha256_archivo(ruta_item))
        )
        avisar(f"{clave}: escrito")

    lock = RAIZ_REPO / "uv.lock"
    return Manifiesto(
        zona=id_zona,
        sha256_config=sha256_bytes((RAIZ_CONFIG / "zonas" / f"{id_zona}.yaml").read_bytes()),
        commit_repo=commit,
        sha256_lockfile=sha256_archivo(lock) if lock.exists() else "",
        items_fuente=[
            ItemFuente(coleccion=it.collection_id, id=it.id, href=it.get_self_href() or "")
            for it in items_s2 + items_s1
        ],
        productos=productos,
    )


def construir_ard_mes(
    id_zona: str,
    destino: Path,
    mes: str,
    ids_bloques: list[str] | None = None,
    avisar: Callable[[str], None] = print,
) -> dict[str, Manifiesto]:
    """Un mes de toda la zona (o de algunos bloques), con S1 de CDSE.

    Cada escena S1 se baja y se corrige una sola vez para toda la zona; luego cada bloque
    lee su ventana. Así una escena no se descarga una vez por bloque.
    """
    from cdcol_fm.ard.bloques import bloques_de_zona
    from cdcol_fm.ard.rtc import rtc_escenas
    from cdcol_fm.fuentes.cdse import es_iw

    zona_completa = cargar_zona(id_zona)
    pais = cargar_pais(zona_completa.pais)
    zona = recortar_zona(zona_completa, None, mes, mes)
    ids = ids_bloques or [b.id for b in bloques_de_zona(zona_completa, pais)]

    items_s1 = [it for it in buscar(S1_GRD_CDSE, zona) if es_iw(it)]
    avisar(f"{mes}: {len(items_s1)} escenas S1 (CDSE GRD) para {len(ids)} bloques")
    trabajo = destino / id_zona / f"_trabajo_{mes}"
    escenas = rtc_escenas(items_s1, zona, pais, trabajo, avisar)
    manifiestos = {}
    try:
        for id_bloque in ids:
            avisar(f"bloque {id_bloque}")
            manifiestos[id_bloque] = construir_ard(
                id_zona,
                destino,
                avisar,
                "cdse",
                id_bloque=id_bloque,
                desde=mes,
                hasta=mes,
                escenas_s1=escenas,
            )
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)
    return manifiestos
