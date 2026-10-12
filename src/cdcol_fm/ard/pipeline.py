"""De la config de una zona al producto ``ard_s1s2_mensual`` escrito en disco, con su manifiesto."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cdcol_fm.ard.compuesto import compuesto_mensual
from cdcol_fm.ard.escritura import PRODUCTO, escribir_mes
from cdcol_fm.ciclo.manifiesto import ItemFuente, Manifiesto, Producto
from cdcol_fm.config import RAIZ_CONFIG, cargar_pais, cargar_zona
from cdcol_fm.fuentes.stac import S1_GRD_CDSE, S1_RTC, S2_L2A, buscar
from cdcol_fm.ingesta.carga import cargar_s1, cargar_s2
from cdcol_fm.linaje.hashes import sha256_archivo, sha256_bytes

RAIZ_REPO = RAIZ_CONFIG.parent


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=RAIZ_REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"


def _mes(item: Any) -> str:
    return str(item.datetime.strftime("%Y-%m"))


def construir_ard(
    id_zona: str,
    destino: Path,
    avisar: Callable[[str], None] = print,
    fuente_s1: str = "pc",
) -> Manifiesto:
    """``fuente_s1``: ``pc`` (RTC de Planetary Computer) o ``cdse`` (GRD + RTC propio)."""
    zona = cargar_zona(id_zona)
    pais = cargar_pais(zona.pais)

    items_s2 = buscar(S2_L2A, zona)
    avisar(f"S2: {len(items_s2)} escenas")
    if not items_s2:
        raise RuntimeError(f"no hay escenas S2 para {id_zona}")
    s2 = cargar_s2(items_s2, zona, pais)
    if fuente_s1 == "cdse":
        from cdcol_fm.ard.rtc import cargar_s1_cdse
        from cdcol_fm.fuentes.cdse import es_iw

        items_s1 = [it for it in buscar(S1_GRD_CDSE, zona) if es_iw(it)]
        avisar(f"S1 (CDSE GRD): {len(items_s1)} escenas")
        trabajo = destino / id_zona / "_trabajo"
        s1 = cargar_s1_cdse(items_s1, zona, pais, trabajo, avisar) if items_s1 else None
        if s1 is not None:
            # misma grilla que S2 por construcción; esto solo absorbe redondeos de coordenadas
            tol = pais.grilla.resolucion_m / 2
            s1 = s1.reindex(x=s2["x"], y=s2["y"], method="nearest", tolerance=tol)
            # rioxarray y odc-stac describen el mismo CRS con atributos distintos: manda el de S2
            s1 = s1.drop_vars("spatial_ref", errors="ignore").load()  # antes de borrar _trabajo
        shutil.rmtree(trabajo, ignore_errors=True)
    elif fuente_s1 == "pc":
        items_s1 = buscar(S1_RTC, zona)
        avisar(f"S1 (PC RTC): {len(items_s1)} escenas")
        s1 = cargar_s1(items_s1, zona, pais) if items_s1 else None
    else:
        raise ValueError(f"fuente_s1 desconocida: {fuente_s1}")
    ard = compuesto_mensual(s2, s1).compute()

    commit = _commit()
    productos = []
    for i in range(ard.sizes["time"]):
        mes = ard.isel(time=i)
        clave = str(mes["time"].values)[:7]
        ids = [it.id for it in items_s2 + items_s1 if _mes(it) == clave]
        item = escribir_mes(mes, destino, id_zona, ids, commit)
        ruta_item = destino / id_zona / PRODUCTO / clave / "item.json"
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
