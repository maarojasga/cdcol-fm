"""Herramientas que el modelo llama para responder: leen el ARD y devuelven números, no píxeles.

Cada herramienta devuelve lo que ve el modelo y, si aplica, una figura para la página (serie o
imágenes sobre el mapa). Una entrada inválida levanta ``ErrorHerramienta``, que vuelve al modelo
como error para que corrija la llamada.
"""

from __future__ import annotations

import tempfile
import warnings
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from cdcol_fm.chat.datos import VARIABLES, Almacen, resumir, valores

MAX_MESES = 24
MAX_BLOQUES = 30
LADO_IMAGEN = 512  # px por bloque en las imágenes del mapa (el COG tiene 1024)
CARPETA_IMAGENES = Path(tempfile.gettempdir()) / "cdcol-chat"

# composiciones de color, además de las variables (que se pintan con una rampa)
COMPOSICIONES = {
    "color": (("B04", "B03", "B02"), (0.0, 1500.0), "Color natural (rojo, verde, azul)"),
    "falso": (("B08", "B04", "B03"), (0.0, 4000.0), "Falso color: la vegetación sana se ve roja"),
}


class ErrorHerramienta(ValueError):
    """Entrada que el modelo puede corregir (zona, mes o variable que no existe, etc.)."""


Resultado = tuple[dict[str, Any], dict[str, Any] | None]  # (para el modelo, figura)


def _seleccion(
    almacen: Almacen, zona: str, meses: list[str] | None, bloques: list[str] | None
) -> dict[str, list[str]]:
    """mes → bloques de la selección que lo tienen calculado."""
    disponibles = almacen.bloques(zona)
    if not disponibles:
        raise ErrorHerramienta(f"la zona '{zona}' no tiene datos; zonas: {almacen.zonas()}")
    bloques = bloques or disponibles
    faltan = sorted(set(bloques) - set(disponibles))
    if faltan:
        raise ErrorHerramienta(f"bloques sin datos en {zona}: {faltan}")
    if len(bloques) > MAX_BLOQUES:
        raise ErrorHerramienta(f"{len(bloques)} bloques; el máximo por consulta es {MAX_BLOQUES}")
    por_mes: dict[str, list[str]] = {}
    for b in bloques:
        for m in almacen.meses(zona, b):
            por_mes.setdefault(m, []).append(b)
    if meses:
        sin = sorted(set(meses) - set(por_mes))
        if sin:
            raise ErrorHerramienta(
                f"meses sin datos para esos bloques: {sin}; hay {sorted(por_mes)}"
            )
        por_mes = {m: por_mes[m] for m in meses}
    if len(por_mes) > MAX_MESES:
        raise ErrorHerramienta(f"{len(por_mes)} meses; el máximo por consulta es {MAX_MESES}")
    return dict(sorted(por_mes.items()))


def _variable(nombre: str) -> None:
    if nombre not in VARIABLES:
        raise ErrorHerramienta(f"variable '{nombre}' no existe; hay {sorted(VARIABLES)}")


def _juntar(almacen: Almacen, zona: str, bloques: list[str], mes: str, variable: str) -> np.ndarray:
    return np.concatenate(
        [valores(almacen, zona, b, mes, variable).ravel() for b in bloques]
    )


def resumen_zona(almacen: Almacen, zona: str) -> Resultado:
    bloques = almacen.bloques(zona)
    if not bloques:
        raise ErrorHerramienta(f"la zona '{zona}' no tiene datos; zonas: {almacen.zonas()}")
    meses = {b: almacen.meses(zona, b) for b in bloques}
    todos = sorted({m for ms in meses.values() for m in ms})
    return {
        "zona": zona,
        "bloques": len(bloques),
        "lado_bloque_km": 10.24,
        "meses_calculados": todos,
        "bloques_por_mes": {m: sum(m in ms for ms in meses.values()) for m in todos},
        "variables": {v.nombre: f"{v.descripcion} [{v.unidad}]" for v in VARIABLES.values()},
    }, None


def estadistica(
    almacen: Almacen,
    zona: str,
    variable: str,
    meses: list[str] | None = None,
    bloques: list[str] | None = None,
) -> Resultado:
    _variable(variable)
    v = VARIABLES[variable]
    por_mes = []
    for mes, bs in _seleccion(almacen, zona, meses, bloques).items():
        resumen = resumir(_juntar(almacen, zona, bs, mes, variable))
        por_mes.append({"mes": mes, "bloques": len(bs), **resumen})
    salida = {"variable": variable, "descripcion": v.descripcion, "unidad": v.unidad,
              "por_mes": por_mes}
    figura = None
    if len(por_mes) >= 2:
        figura = {"tipo": "serie", "variable": variable, "unidad": v.unidad,
                  "puntos": [{k: p[k] for k in ("mes", "p10", "p50", "p90")} for p in por_mes]}
    return salida, figura


def calidad(
    almacen: Almacen, zona: str, meses: list[str] | None = None, bloques: list[str] | None = None
) -> Resultado:
    filas = []
    for mes, bs in _seleccion(almacen, zona, meses, bloques).items():
        n = _juntar(almacen, zona, bs, mes, "n_validas_s2")
        nube = _juntar(almacen, zona, bs, mes, "prob_nube")
        dias = _juntar(almacen, zona, bs, mes, "dias_desde_clara")
        vv = _juntar(almacen, zona, bs, mes, "vv")
        filas.append({
            "mes": mes,
            "bloques": len(bs),
            "sin_vista_optica_limpia_pct": round(100 * float(np.mean(~(n > 0))), 1),
            "observaciones_limpias_p50": resumir(n)["p50"],
            "nube_media_pct": resumir(nube)["media"],
            "dias_desde_clara_p50": resumir(dias)["p50"],
            "radar_con_dato_pct": round(100 * float(np.mean(np.isfinite(vv))), 1),
        })
    figura = None
    if len(filas) >= 2:
        figura = {"tipo": "serie", "variable": "sin vista óptica limpia", "unidad": "%",
                  "puntos": [{"mes": f["mes"], "p50": f["sin_vista_optica_limpia_pct"]}
                             for f in filas]}
    return {"por_mes": filas, "nota": "Sin vista limpia: el píxel no tuvo ninguna observación "
            "óptica sin nube en el mes; ahí el óptico es relleno o no hay dato. El radar ve a "
            "través de las nubes."}, figura


def _pct(condicion: np.ndarray) -> float:
    return round(100 * float(np.mean(condicion)), 1)


def comparar(
    almacen: Almacen,
    zona: str,
    variable: str,
    mes_a: str,
    mes_b: str,
    bloques: list[str] | None = None,
) -> Resultado:
    _variable(variable)
    sel = _seleccion(almacen, zona, [mes_a, mes_b], bloques)
    comunes = sorted(set(sel[mes_a]) & set(sel[mes_b]))
    if not comunes:
        raise ErrorHerramienta(f"ningún bloque tiene a la vez {mes_a} y {mes_b}")
    a = _juntar(almacen, zona, comunes, mes_a, variable)
    b = _juntar(almacen, zona, comunes, mes_b, variable)
    dif = b - a
    ambos = np.isfinite(dif)
    bajo, alto = VARIABLES[variable].rango
    umbral = 0.1 * (alto - bajo)
    cambios = dif[ambos]
    return {
        "variable": variable,
        "unidad": VARIABLES[variable].unidad,
        "bloques": len(comunes),
        mes_a: resumir(a),
        mes_b: resumir(b),
        "diferencia_b_menos_a": resumir(dif),
        "pixeles_con_ambos_pct": round(100 * float(ambos.mean()), 1),
        "umbral_cambio_notable": umbral,
        "subio_notable_pct": _pct(cambios > umbral) if cambios.size else None,
        "bajo_notable_pct": _pct(cambios < -umbral) if cambios.size else None,
    }, None


@lru_cache(maxsize=8)
def _transformador(crs: str) -> Any:
    from pyproj import Transformer

    return Transformer.from_crs(crs, "EPSG:4326", always_xy=True)


def esquinas(id_bloque: str, zona: str) -> list[list[float]]:
    """[lon, lat] de las esquinas: noroeste, noreste, sureste, suroeste (orden de MapLibre)."""
    from cdcol_fm.ard.bloques import bloque as cargar_bloque
    from cdcol_fm.config import cargar_pais, cargar_zona

    try:
        pais = cargar_pais(cargar_zona(zona).pais)
    except FileNotFoundError:
        pais = cargar_pais("colombia")
    oeste, sur, este, norte = cargar_bloque(id_bloque, pais).limites
    t = _transformador(pais.grilla.crs)
    return [[round(c, 6) for c in t.transform(x, y)]
            for x, y in ((oeste, norte), (este, norte), (este, sur), (oeste, sur))]


def _imagen(almacen: Almacen, zona: str, bloque: str, mes: str, capa: str) -> Path:
    from cdcol_fm.ard.vista import _a_bytes, _png, _rampa

    ruta = CARPETA_IMAGENES / zona / f"{bloque}_{mes}_{capa}.png"
    if ruta.exists():
        return ruta
    if capa in COMPOSICIONES:
        bandas, rango, _ = COMPOSICIONES[capa]
        leidas = [valores(almacen, zona, bloque, mes, b.lower(), LADO_IMAGEN) * 10_000
                  for b in bandas]
        img = np.stack([_a_bytes(x, rango) for x in leidas])
    else:
        img = _rampa(valores(almacen, zona, bloque, mes, capa, LADO_IMAGEN), VARIABLES[capa].rango)
    with warnings.catch_warnings():
        # un PNG para el navegador no lleva georreferencia: la ubican las esquinas
        warnings.filterwarnings("ignore", message="Dataset has no geotransform")
        _png(img, ruta)
    return ruta


def mapa(
    almacen: Almacen, zona: str, capa: str, mes: str, bloques: list[str] | None = None
) -> Resultado:
    if capa not in COMPOSICIONES:
        _variable(capa)
    bs = _seleccion(almacen, zona, [mes], bloques)[mes]
    piezas = []
    for b in bs:
        ruta = _imagen(almacen, zona, b, mes, capa)
        piezas.append({"bloque": b, "imagen": f"{zona}/{ruta.name}", "esquinas": esquinas(b, zona)})
    if capa in COMPOSICIONES:
        leyenda = COMPOSICIONES[capa][2]
    else:
        v = VARIABLES[capa]
        unidad = f" {v.unidad}" if v.unidad else ""
        leyenda = f"{v.descripcion}: morado = {v.rango[0]:g}, amarillo = {v.rango[1]:g}{unidad}"
    return (
        {"capa": capa, "mes": mes, "bloques_pintados": len(piezas), "leyenda": leyenda,
         "nota": "La imagen ya se muestra sobre el mapa de la página."},
        {"tipo": "mapa", "capa": capa, "mes": mes, "leyenda": leyenda, "piezas": piezas},
    )


_SELECCION = {
    "zona": {"type": "string", "description": "Id de la zona, p. ej. 'macarena'"},
    "bloques": {"type": "array", "items": {"type": "string"},
                "description": "Ids de bloque (x<col>_y<fila>). Omitir = toda la selección del "
                               "mapa o, si no hay, todos los bloques de la zona"},
}
_MESES = {"type": "array", "items": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
          "description": "Meses AAAA-MM. Omitir = todos los calculados"}
_VARIABLE = {"type": "string", "enum": sorted(VARIABLES)}

HERRAMIENTAS: dict[str, tuple[Callable[..., Resultado], dict[str, Any]]] = {
    "resumen_zona": (resumen_zona, {
        "description": "Qué hay calculado en una zona: bloques, meses y variables disponibles. "
                       "Úsala primero si no sabes qué meses existen.",
        "input_schema": {"type": "object", "properties": {"zona": _SELECCION["zona"]},
                         "required": ["zona"], "additionalProperties": False},
    }),
    "estadistica": (estadistica, {
        "description": "Media, p10, p50, p90 y % de píxeles con dato de una variable, mes por "
                       "mes, sobre los bloques pedidos. Sirve para niveles y series de tiempo.",
        "input_schema": {"type": "object", "properties": {
            **_SELECCION, "variable": _VARIABLE, "meses": _MESES},
            "required": ["zona", "variable"], "additionalProperties": False},
    }),
    "calidad": (calidad, {
        "description": "Confiabilidad de los datos por mes: % sin vista óptica limpia, "
                       "observaciones limpias, nube, días desde la última vista clara y cobertura "
                       "de radar. Úsala antes de concluir algo con variables ópticas.",
        "input_schema": {"type": "object", "properties": {**_SELECCION, "meses": _MESES},
                         "required": ["zona"], "additionalProperties": False},
    }),
    "comparar": (comparar, {
        "description": "Cambio de una variable entre dos meses en los mismos píxeles: resumen "
                       "de cada mes, de la diferencia (b − a) y % de píxeles con cambio notable.",
        "input_schema": {"type": "object", "properties": {
            **_SELECCION, "variable": _VARIABLE,
            "mes_a": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
            "mes_b": {"type": "string", "pattern": r"^\d{4}-\d{2}$"}},
            "required": ["zona", "variable", "mes_a", "mes_b"], "additionalProperties": False},
    }),
    "mapa": (mapa, {
        "description": "Pinta una capa de un mes sobre el mapa de la página. 'color' y 'falso' "
                       "son composiciones RGB; las variables se pintan con una rampa de colores.",
        "input_schema": {"type": "object", "properties": {
            **_SELECCION, "capa": {"type": "string", "enum": sorted([*COMPOSICIONES, *VARIABLES])},
            "mes": {"type": "string", "pattern": r"^\d{4}-\d{2}$"}},
            "required": ["zona", "capa", "mes"], "additionalProperties": False},
    }),
}


def definiciones() -> list[dict[str, Any]]:
    """Las herramientas en el formato de la API, en orden fijo (para la caché del prompt)."""
    return [{"name": nombre, **d} for nombre, (_, d) in HERRAMIENTAS.items()]


def ejecutar(almacen: Almacen, nombre: str, entrada: dict[str, Any]) -> Resultado:
    if nombre not in HERRAMIENTAS:
        raise ErrorHerramienta(f"herramienta desconocida: {nombre}")
    funcion, definicion = HERRAMIENTAS[nombre]
    permitidas = definicion["input_schema"]["properties"]
    extra = sorted(set(entrada) - set(permitidas))
    if extra:
        raise ErrorHerramienta(f"parámetros desconocidos: {extra}")
    faltan = [p for p in definicion["input_schema"]["required"] if p not in entrada]
    if faltan:
        raise ErrorHerramienta(f"faltan parámetros: {faltan}")
    return funcion(almacen, **entrada)
