"""Corrida de un experimento: pliegues por bloque × semillas × presupuestos de etiquetas.

``evaluar`` y ``veredicto`` son puros (arreglos en memoria) y se prueban sin datos reales.
``cargar_datos`` lee el ARD, los embeddings y la referencia de disco.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from cdcol_fm.bench.brazos import Clasificador, crear
from cdcol_fm.bench.experimento import Experimento
from cdcol_fm.bench.metricas import METRICAS, brechas_bootstrap, ic95
from cdcol_fm.bench.muestreo import (
    SIN_CLASE,
    asignar_estratos,
    cortes_por_cuantiles,
    homogeneo,
    muestra_de_prueba,
    muestrear_por_clase,
    pliegues_por_bloque,
    reclasificar,
)

# Píxeles elegibles por clase y bloque que se guardan en memoria (los rasgos de un bloque
# completo no caben para 15+ bloques). Fijo con semilla 0: no depende de la semilla del brazo.
CANDIDATOS_POR_CLASE_Y_BLOQUE = 20_000


@dataclass
class Datos:
    """Un elemento por píxel candidato. ``rasgos`` solo trae los brazos que tienen datos."""

    clases: np.ndarray
    estratos: np.ndarray
    bloques: np.ndarray
    rasgos: dict[str, np.ndarray]
    cortes_estratos: np.ndarray = field(default_factory=lambda: np.array([]))
    # (bloque, estrato, clase) → píxeles elegibles del bloque completo, antes de submuestrear
    # candidatos. Solo para explicar una prueba insuficiente.
    elegibles: dict[tuple[str, int, int], int] = field(default_factory=dict)


class PruebaInsuficiente(ValueError):
    """Algún pliegue no tiene la prueba pre-registrada en algún estrato y clase."""


def verificar_prueba(exp: Experimento, datos: Datos) -> None:
    """Falla si en algún pliegue × estrato × clase hay menos candidatos que
    ``prueba_por_clase_y_estrato``: muestrear menos sin avisar cambiaría el pre-registro.
    """
    ev = exp.evaluacion
    pliegue_de = pliegues_por_bloque(sorted(set(datos.bloques.tolist())), ev.pliegues)
    pliegue = np.array([pliegue_de[b] for b in datos.bloques])
    faltas = []
    for f in range(ev.pliegues):
        bloques_f = sorted(b for b, pf in pliegue_de.items() if pf == f)
        for e, nombre in enumerate(exp.estratos.nombres):
            for clase, nombre_clase in sorted(exp.clases.items()):
                sel = (pliegue == f) & (datos.estratos == e) & (datos.clases == clase)
                n = int(sel.sum())
                if n < ev.prueba_por_clase_y_estrato:
                    total = sum(datos.elegibles.get((b, e, clase), 0) for b in bloques_f)
                    faltas.append(
                        f"  pliegue {f} ({', '.join(bloques_f)}), {nombre}, {nombre_clase}: "
                        f"{n} candidatos de {total} elegibles"
                    )
    if faltas:
        raise PruebaInsuficiente(
            f"{exp.id}: hacen falta {ev.prueba_por_clase_y_estrato} píxeles de prueba por clase "
            "y estrato en cada pliegue, y no alcanzan en:\n"
            + "\n".join(faltas)
            + "\nNo se muestrea menos sin avisar: se decide y se anota en el README antes de "
            "correr. Si los elegibles alcanzan y los candidatos no, el límite es "
            "CANDIDATOS_POR_CLASE_Y_BLOQUE."
        )


@dataclass
class Predicciones:
    """Predicciones fuera de pliegue de un presupuesto, apiladas sobre semillas."""

    real: list[np.ndarray] = field(default_factory=list)
    estrato: list[np.ndarray] = field(default_factory=list)
    bloque: list[np.ndarray] = field(default_factory=list)
    pred: dict[str, list[np.ndarray]] = field(default_factory=dict)

    def apilar(self) -> dict[str, np.ndarray]:
        salida = {
            "real": np.concatenate(self.real),
            "estrato": np.concatenate(self.estrato),
            "bloque": np.concatenate(self.bloque),
        }
        salida.update({f"pred:{b}": np.concatenate(p) for b, p in self.pred.items()})
        return salida


def evaluar(
    exp: Experimento,
    datos: Datos,
    crear_brazo: Callable[[str, int], Clasificador] = crear,
) -> tuple[list[dict[str, Any]], dict[int, Predicciones]]:
    """Filas de resultados y predicciones fuera de pliegue por presupuesto.

    Todos los brazos se entrenan con los mismos píxeles y se prueban en los mismos píxeles.
    """
    ev = exp.evaluacion
    verificar_prueba(exp, datos)
    metrica = METRICAS[ev.metrica]
    brazos = [b for b in exp.brazos if b.id in datos.rasgos]
    pliegue_de = pliegues_por_bloque(sorted(set(datos.bloques.tolist())), ev.pliegues)
    pliegue = np.array([pliegue_de[b] for b in datos.bloques])
    filas: list[dict[str, Any]] = []
    preds = {n: Predicciones() for n in ev.etiquetas_por_clase}
    for semilla in ev.semillas:
        rng = np.random.default_rng(semilla)
        for f in range(ev.pliegues):
            en_prueba = pliegue == f
            prueba = muestra_de_prueba(
                datos.clases, datos.estratos, ev.prueba_por_clase_y_estrato, rng, en_prueba
            )
            if prueba.size == 0:
                continue
            for n in ev.etiquetas_por_clase:
                entreno = muestrear_por_clase(datos.clases, n, rng, ~en_prueba)
                p = preds[n]
                p.real.append(datos.clases[prueba])
                p.estrato.append(datos.estratos[prueba])
                p.bloque.append(datos.bloques[prueba])
                for brazo in brazos:
                    x = datos.rasgos[brazo.id]
                    modelo = crear_brazo(brazo.tipo, semilla)
                    modelo.fit(x[entreno], datos.clases[entreno])
                    pred = modelo.predict(x[prueba])
                    p.pred.setdefault(brazo.id, []).append(pred)
                    for e, nombre in enumerate(exp.estratos.nombres):
                        sel = datos.estratos[prueba] == e
                        filas.append(
                            {
                                "brazo": brazo.id,
                                "semilla": semilla,
                                "pliegue": f,
                                "etiquetas_por_clase": n,
                                "estrato": nombre,
                                "n_prueba": int(sel.sum()),
                                ev.metrica: metrica(datos.clases[prueba][sel], pred[sel])
                                if sel.any()
                                else float("nan"),
                            }
                        )
    return filas, preds


def veredicto(exp: Experimento, preds: dict[int, Predicciones]) -> tuple[str, dict[str, Any]]:
    """Aplica el criterio de decisión del README al presupuesto principal."""
    ev = exp.evaluacion
    ref = exp.brazo_referencia
    nombres = exp.estratos.nombres
    p = preds[ev.presupuesto_principal]
    lineas = [f"# Veredicto {exp.id}", "", f"Presupuesto: {ev.presupuesto_principal} por clase."]
    resultado: dict[str, Any] = {}
    # un brazo externo (p. ej. AlphaEarth) no bloquea el veredicto: si no tiene datos, se omite
    otros = [b for b in exp.brazos if not b.referencia and (not b.externo or b.id in p.pred)]
    faltan = [b.id for b in otros if b.id not in p.pred] + (
        [ref.id] if ref.id not in p.pred else []
    )
    if faltan or not p.real:
        lineas += ["", f"Sin veredicto: faltan datos de {', '.join(faltan) or 'prueba'}."]
        return "\n".join(lineas) + "\n", {"faltan": faltan}
    d = p.apilar()
    nublado, despejado = 0, len(nombres) - 1
    for brazo in otros:
        puntual, replicas = brechas_bootstrap(
            d["real"],
            d[f"pred:{brazo.id}"],
            d[f"pred:{ref.id}"],
            d["estrato"],
            d["bloque"],
            METRICAS[ev.metrica],
            ev.bootstrap,
        )
        lineas += [
            "",
            f"## {brazo.id} − {ref.id}",
            "",
            "| Estrato | Brecha | IC 95 % |",
            "|---|---|---|",
        ]
        for e, nombre in enumerate(nombres):
            bajo, alto = ic95(replicas[:, e])
            lineas.append(f"| {nombre} | {puntual[e]:+.3f} | [{bajo:+.3f}, {alto:+.3f}] |")
        if brazo.externo:
            lineas += ["", "- Línea base externa: se reporta, no decide H1 ni H2."]
            resultado[brazo.id] = {"externo": True, "brecha": puntual.tolist()}
            continue
        bajo, alto = ic95(replicas[:, nublado])
        if alto < 0:
            h1 = "apoyada"
        elif bajo > -ev.delta:
            h1 = "refutada"
        else:
            h1 = "no concluyente"
        dif_b, dif_a = ic95(replicas[:, nublado] - replicas[:, despejado])
        h2 = "apoyada" if dif_a < 0 else "no apoyada"
        lineas += [
            "",
            f"- H1 (degradación en {nombres[nublado]}): **{h1}**",
            f"- H2 (brecha {nombres[nublado]} − {nombres[despejado]} = "
            f"{puntual[nublado] - puntual[despejado]:+.3f}, IC [{dif_b:+.3f}, {dif_a:+.3f}]): "
            f"**{h2}**",
        ]
        resultado[brazo.id] = {"h1": h1, "h2": h2, "brecha": puntual.tolist()}
    return "\n".join(lineas) + "\n", resultado


# --- Lectura de disco -------------------------------------------------------------------


def _serie_bloque(base: Path, anio: int, solo: tuple[str, ...] | None = None) -> Any:
    """ARD mensual de un bloque (time, y, x) leído de sus COG."""
    import rioxarray
    import xarray as xr

    from cdcol_fm.ard.bandas import BANDAS_ARD

    meses = sorted(p for p in base.glob(f"{anio}-*") if p.is_dir())
    if not meses:
        raise FileNotFoundError(f"no hay meses de {anio} en {base}")
    capas = []
    for carpeta in meses:
        bandas = {}
        for banda in solo or BANDAS_ARD:
            da = rioxarray.open_rasterio(carpeta / f"{banda}.tif")
            assert isinstance(da, xr.DataArray)
            bandas[banda] = da.squeeze("band", drop=True)
        capas.append(
            xr.Dataset(bandas).expand_dims(time=[np.datetime64(f"{carpeta.name}-01", "ns")])
        )
    return xr.concat(capas, dim="time")


@dataclass
class CortesEstratos:
    cortes: np.ndarray
    pixeles: int  # todos los píxeles de los bloques
    sin_dato: int  # sin n_validas_s2 ningún mes: fuera de los estratos


def _n_validas_bloque(exp: Experimento, destino: Path, id_bloque: str) -> np.ndarray:
    from cdcol_fm.ard.escritura import carpeta_producto
    from cdcol_fm.bench.rasgos import n_validas_anual

    base = carpeta_producto(destino, exp.zona, id_bloque)
    serie = _serie_bloque(base, exp.anio, ("n_validas_s2",))
    meses = serie.sizes["time"]
    if meses != 12:
        raise ValueError(f"{id_bloque}: {meses} meses de {exp.anio} en {base}; hacen falta 12")
    return n_validas_anual(serie)


def calcular_cortes(exp: Experimento, destino: Path) -> CortesEstratos:
    """Cortes de los estratos sobre todos los píxeles de los bloques que tienen valor.

    Solo lee ``n_validas_s2`` del ARD: no depende de la referencia ni de ningún brazo.
    """
    valores = np.concatenate([_n_validas_bloque(exp, destino, b) for b in exp.bloques])
    return CortesEstratos(
        cortes=cortes_por_cuantiles(valores, len(exp.estratos.nombres)),
        pixeles=int(valores.size),
        sin_dato=int((~np.isfinite(valores)).sum()),
    )


def cargar_datos(exp: Experimento, destino: Path, raiz_repo: Path | None = None) -> Datos:
    """Candidatos de todos los bloques del experimento, con estratos y rasgos por brazo.

    Los estratos usan los cortes fijados en el config; si el ARD ya no da esos cortes, falla.
    Un brazo cuyos rasgos no están en disco (p. ej. embeddings sin calcular) queda fuera.
    """
    import rioxarray
    import xarray as xr
    from rasterio.enums import Resampling  # type: ignore[import-untyped]

    from cdcol_fm.ard.escritura import carpeta_producto
    from cdcol_fm.bench.rasgos import ard_anual, n_validas_anual

    if len(exp.bloques) < 2 * exp.evaluacion.pliegues:
        raise ValueError(
            f"{exp.id}: {len(exp.bloques)} bloques; hacen falta al menos "
            f"{2 * exp.evaluacion.pliegues} (fijarlos en config.yaml)"
        )
    if exp.estratos.cortes is None:
        raise ValueError(
            f"{exp.id}: faltan los cortes de los estratos; fijarlos con "
            f"`cdcol estratos {exp.id} --escribir` antes de cargar la referencia"
        )
    cortes = np.array(exp.estratos.cortes)
    ruta_ref = exp.referencia.ruta
    if not ruta_ref.is_absolute() and raiz_repo is not None:
        ruta_ref = raiz_repo / ruta_ref
    if not ruta_ref.exists():
        raise FileNotFoundError(f"falta la referencia {ruta_ref} (ver README del experimento)")
    referencia = rioxarray.open_rasterio(ruta_ref)
    assert isinstance(referencia, xr.DataArray)
    referencia = referencia.squeeze("band", drop=True)

    rng = np.random.default_rng(0)
    partes: dict[str, list[np.ndarray]] = {"clases": [], "estratos": [], "bloques": []}
    rasgos: dict[str, list[np.ndarray]] = {}
    nvalidas_todas = []
    elegibles: dict[tuple[str, int, int], int] = {}
    for id_bloque in exp.bloques:
        serie = _serie_bloque(carpeta_producto(destino, exp.zona, id_bloque), exp.anio)
        plantilla = serie["n_validas_s2"].isel(time=0)
        codigos = referencia.rio.reproject_match(plantilla, resampling=Resampling.nearest)
        r = exp.referencia
        clases = reclasificar(np.asarray(codigos), r.reclasificacion, r.otros_a, r.nodata)
        elegible = homogeneo(clases, r.radio_homogeneo).ravel()
        clases = clases.ravel()
        nvalidas = n_validas_anual(serie)
        nvalidas_todas.append(nvalidas)
        estratos = asignar_estratos(nvalidas, cortes)
        # un píxel sin valor de nubosidad no tiene estrato: no es candidato
        elegible &= estratos >= 0
        for e in range(len(exp.estratos.nombres)):
            for clase in exp.clases:
                n = int((elegible & (estratos == e) & (clases == clase)).sum())
                elegibles[(id_bloque, e, clase)] = n
        idx = muestrear_por_clase(clases, CANDIDATOS_POR_CLASE_Y_BLOQUE, rng, elegible)
        partes["clases"].append(clases[idx])
        partes["estratos"].append(estratos[idx])
        partes["bloques"].append(np.full(idx.size, id_bloque))
        x_ard, _ = ard_anual(serie)
        for brazo in exp.brazos:
            if brazo.rasgos == "ard-anual":
                rasgos.setdefault(brazo.id, []).append(x_ard[idx])
            # los brazos de embeddings se agregan cuando exista `cdcol embeber` (fase 2)
    recalculados = cortes_por_cuantiles(np.concatenate(nvalidas_todas), len(cortes) + 1)
    if not np.allclose(recalculados, cortes):
        raise ValueError(
            f"{exp.id}: el ARD da cortes {recalculados.tolist()}, pero el config fija "
            f"{cortes.tolist()}: el ARD cambió después de fijarlos"
        )
    clases = np.concatenate(partes["clases"])
    assert not np.any(clases == SIN_CLASE)
    return Datos(
        clases=clases,
        estratos=np.concatenate(partes["estratos"]),
        bloques=np.concatenate(partes["bloques"]),
        rasgos={b: np.concatenate(x) for b, x in rasgos.items()},
        cortes_estratos=cortes,
        elegibles=elegibles,
    )


def guardar(
    exp: Experimento, filas: list[dict[str, Any]], texto: str, datos: Datos, carpeta: Path
) -> None:
    import csv
    import json

    carpeta.mkdir(parents=True, exist_ok=True)
    with (carpeta / "resultados.csv").open("w", newline="", encoding="utf-8") as f:
        if filas:
            escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
            escritor.writeheader()
            escritor.writerows(filas)
    (carpeta / "veredicto.md").write_text(texto, encoding="utf-8")
    contexto = {
        "experimento": exp.id,
        "cortes_estratos_n_validas_anual": datos.cortes_estratos.tolist(),
        "elegibles_bloque_estrato_clase": {
            f"{b}|{exp.estratos.nombres[e]}|{exp.clases[c]}": n
            for (b, e, c), n in sorted(datos.elegibles.items())
        },
        "candidatos": int(datos.clases.size),
        "brazos_con_datos": sorted(datos.rasgos),
    }
    (carpeta / "contexto.json").write_text(json.dumps(contexto, indent=2), encoding="utf-8")
