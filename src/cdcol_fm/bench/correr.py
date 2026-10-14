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
    estratos_por_cuantiles,
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
    otros = [b for b in exp.brazos if not b.referencia]
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


def _serie_bloque(base: Path, anio: int) -> Any:
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
        for banda in BANDAS_ARD:
            da = rioxarray.open_rasterio(carpeta / f"{banda}.tif")
            assert isinstance(da, xr.DataArray)
            bandas[banda] = da.squeeze("band", drop=True)
        capas.append(
            xr.Dataset(bandas).expand_dims(time=[np.datetime64(f"{carpeta.name}-01", "ns")])
        )
    return xr.concat(capas, dim="time")


def cargar_datos(exp: Experimento, destino: Path, raiz_repo: Path | None = None) -> Datos:
    """Candidatos de todos los bloques del experimento, con estratos y rasgos por brazo.

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
    ruta_ref = exp.referencia.ruta
    if not ruta_ref.is_absolute() and raiz_repo is not None:
        ruta_ref = raiz_repo / ruta_ref
    if not ruta_ref.exists():
        raise FileNotFoundError(f"falta la referencia {ruta_ref} (ver README del experimento)")
    referencia = rioxarray.open_rasterio(ruta_ref)
    assert isinstance(referencia, xr.DataArray)
    referencia = referencia.squeeze("band", drop=True)

    rng = np.random.default_rng(0)
    partes: dict[str, list[np.ndarray]] = {"clases": [], "nvalidas": [], "bloques": []}
    rasgos: dict[str, list[np.ndarray]] = {}
    for id_bloque in exp.bloques:
        serie = _serie_bloque(carpeta_producto(destino, exp.zona, id_bloque), exp.anio)
        plantilla = serie["n_validas_s2"].isel(time=0)
        codigos = referencia.rio.reproject_match(plantilla, resampling=Resampling.nearest)
        r = exp.referencia
        clases = reclasificar(np.asarray(codigos), r.reclasificacion, r.otros_a, r.nodata)
        elegible = homogeneo(clases, r.radio_homogeneo).ravel()
        clases = clases.ravel()
        idx = muestrear_por_clase(clases, CANDIDATOS_POR_CLASE_Y_BLOQUE, rng, elegible)
        partes["clases"].append(clases[idx])
        partes["nvalidas"].append(n_validas_anual(serie)[idx])
        partes["bloques"].append(np.full(idx.size, id_bloque))
        x_ard, _ = ard_anual(serie)
        for brazo in exp.brazos:
            if brazo.rasgos == "ard-anual":
                rasgos.setdefault(brazo.id, []).append(x_ard[idx])
            # los brazos de embeddings se agregan cuando exista `cdcol embeber` (fase 2)
    estratos, cortes = estratos_por_cuantiles(
        np.concatenate(partes["nvalidas"]), len(exp.estratos.nombres)
    )
    clases = np.concatenate(partes["clases"])
    assert not np.any(clases == SIN_CLASE)
    return Datos(
        clases=clases,
        estratos=estratos,
        bloques=np.concatenate(partes["bloques"]),
        rasgos={b: np.concatenate(x) for b, x in rasgos.items()},
        cortes_estratos=cortes,
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
        "candidatos": int(datos.clases.size),
        "brazos_con_datos": sorted(datos.rasgos),
    }
    (carpeta / "contexto.json").write_text(json.dumps(contexto, indent=2), encoding="utf-8")
