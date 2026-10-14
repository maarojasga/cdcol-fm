"""El veredicto con datos sintéticos donde la respuesta se conoce de antemano."""

from typing import Any

import numpy as np
import pytest
import xarray as xr

from cdcol_fm.bench.correr import Datos, evaluar, veredicto
from cdcol_fm.bench.experimento import cargar_experimento


class CentroideMasCercano:
    """Clasificador mínimo y determinista para no depender de sklearn en estas pruebas."""

    def fit(self, x: np.ndarray, y: np.ndarray) -> "CentroideMasCercano":
        self.clases = np.unique(y)
        self.centros = np.stack([x[y == c].mean(axis=0) for c in self.clases])
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        d = ((x[:, None, :] - self.centros[None]) ** 2).sum(axis=-1)
        return np.asarray(self.clases[d.argmin(axis=1)])


def _crear(tipo: str, semilla: int) -> Any:
    return CentroideMasCercano()


def _exp() -> Any:
    exp = cargar_experimento("e01")
    ev = exp.evaluacion.model_copy(
        update={
            "etiquetas_por_clase": [20],
            "presupuesto_principal": 20,
            "semillas": [0, 1],
            "bootstrap": 300,
            "prueba_por_clase_y_estrato": 100,
        }
    )
    return exp.model_copy(update={"evaluacion": ev})


def _datos(fm_falla_con_nube: bool) -> Datos:
    rng = np.random.default_rng(1)
    n_bloques, por_bloque = 12, 600
    n = n_bloques * por_bloque
    clases = rng.integers(0, 2, n)
    estratos = rng.integers(0, 3, n)
    bloques = np.repeat([f"x{i}_y0" for i in range(n_bloques)], por_bloque)
    senal = clases[:, None] * 2.0 + rng.normal(0, 0.5, (n, 4))
    fm = senal.copy()
    if fm_falla_con_nube:
        # en el estrato nublado (0) los rasgos del fundacional no tienen señal
        nublado = estratos == 0
        fm[nublado] = rng.normal(1.0, 0.5, (int(nublado.sum()), 4))
    return Datos(
        clases=clases,
        estratos=estratos,
        bloques=bloques,
        rasgos={"local-rf": senal, "galileo-r0-sonda": fm},
    )


def test_detecta_la_degradacion_cuando_existe() -> None:
    exp = _exp()
    filas, preds = evaluar(exp, _datos(fm_falla_con_nube=True), _crear)
    texto, resultado = veredicto(exp, preds)
    assert resultado["galileo-r0-sonda"]["h1"] == "apoyada"
    assert resultado["galileo-r0-sonda"]["h2"] == "apoyada"
    assert "nublado" in texto
    assert {f["brazo"] for f in filas} == {"local-rf", "galileo-r0-sonda"}


def test_no_la_inventa_cuando_no_existe() -> None:
    exp = _exp()
    _, preds = evaluar(exp, _datos(fm_falla_con_nube=False), _crear)
    _, resultado = veredicto(exp, preds)
    assert resultado["galileo-r0-sonda"]["h1"] == "refutada"
    assert resultado["galileo-r0-sonda"]["h2"] == "no apoyada"


def test_sin_embeddings_no_hay_veredicto() -> None:
    exp = _exp()
    datos = _datos(fm_falla_con_nube=False)
    datos.rasgos.pop("galileo-r0-sonda")
    filas, preds = evaluar(exp, datos, _crear)
    texto, resultado = veredicto(exp, preds)
    assert resultado == {"faltan": ["galileo-r0-sonda"]}
    assert "Sin veredicto" in texto
    assert filas and {f["brazo"] for f in filas} == {"local-rf"}


def test_brazos_reales_de_sklearn() -> None:
    pytest.importorskip("sklearn")
    from cdcol_fm.bench.brazos import crear

    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 200)
    x = y[:, None] + rng.normal(0, 0.3, (200, 3))
    x[::7, 1] = np.nan  # meses sin dato
    for tipo in ("bosque-aleatorio", "sonda-lineal"):
        modelo = crear(tipo, 0).fit(x, y)
        assert (modelo.predict(x) == y).mean() > 0.9
    with pytest.raises(ValueError):
        crear("otro", 0)


def test_rasgos_anuales_ignoran_meses_sin_dato() -> None:
    from cdcol_fm.ard.bandas import BANDAS_ARD
    from cdcol_fm.bench.rasgos import ard_anual, n_validas_anual

    t = np.array(["2024-01-01", "2024-02-01", "2024-03-01"], dtype="datetime64[ns]")
    ds = xr.Dataset(coords={"time": t, "y": [1.0, 0.0], "x": [0.0, 1.0]})
    for b in BANDAS_ARD:
        ds[b] = (("time", "y", "x"), np.ones((3, 2, 2), dtype="float32"))
    ds["B04"][:] = np.array([100, 0, 300], dtype="float32")[:, None, None]  # febrero sin dato
    ds["n_validas_s2"][:] = np.array([2, 255, 1], dtype="float32")[:, None, None]
    x, nombres = ard_anual(ds)
    assert x.shape == (4, len(nombres)) and len(nombres) == 12 * 3
    assert x[0, nombres.index("B04_p50")] == pytest.approx(200)
    assert n_validas_anual(ds).tolist() == [3, 3, 3, 3]


def test_de_disco_a_veredicto(tmp_path: Any) -> None:
    """ARD escrito con escribir_mes + referencia GeoTIFF → cargar_datos → evaluar."""
    import pandas as pd
    import rioxarray  # noqa: F401

    from cdcol_fm.ard.bandas import BANDAS_ARD
    from cdcol_fm.ard.escritura import escribir_mes
    from cdcol_fm.bench.correr import cargar_datos

    lado, res = 16, 10.0
    bloques = [f"x{i}_y0" for i in range(4)]
    rng = np.random.default_rng(0)
    # referencia: mitad oeste de cada bloque bosque (código 3), mitad este pasto (15)
    ancho_total = lado * len(bloques)
    codigos = np.where(np.arange(ancho_total) % lado < lado // 2, 3, 15)
    ref = xr.DataArray(
        np.tile(codigos, (lado, 1)).astype("uint8"),
        dims=("y", "x"),
        coords={
            "y": 1000.0 - res * (np.arange(lado) + 0.5),
            "x": res * (np.arange(ancho_total) + 0.5),
        },
    ).rio.write_crs("EPSG:9377")
    ruta_ref = tmp_path / "ref.tif"
    ref.rio.to_raster(ruta_ref)

    for i, b in enumerate(bloques):
        x = res * (i * lado + np.arange(lado) + 0.5)
        y = 1000.0 - res * (np.arange(lado) + 0.5)
        bosque = (np.arange(lado) < lado // 2)[None, :].repeat(lado, 0)
        for mes in ("2024-01", "2024-02"):
            ds = xr.Dataset(coords={"time": pd.Timestamp(f"{mes}-01"), "y": y, "x": x})
            for banda in BANDAS_ARD:
                ds[banda] = (("y", "x"), np.ones((lado, lado), dtype="float32"))
            ds["B08"] = (("y", "x"), np.where(bosque, 3000, 1500) + rng.normal(0, 50, (lado, lado)))
            ds["n_validas_s2"] = (("y", "x"), rng.integers(0, 4, (lado, lado)).astype("uint8"))
            ds["dias_desde_clara"] = ds["dias_desde_clara"].astype("uint16")
            ds["prob_nube"] = ds["prob_nube"].astype("uint8")
            ds["n_adq_s1"] = ds["n_adq_s1"].astype("uint8")
            escribir_mes(ds.rio.write_crs("EPSG:9377"), tmp_path, "macarena", [], "abc", b)

    exp = _exp()
    exp = exp.model_copy(
        update={
            "bloques": bloques,
            "evaluacion": exp.evaluacion.model_copy(
                update={"pliegues": 2, "etiquetas_por_clase": [5], "presupuesto_principal": 5}
            ),
            "referencia": exp.referencia.model_copy(
                update={"ruta": ruta_ref, "radio_homogeneo": 1}
            ),
        }
    )
    datos = cargar_datos(exp, tmp_path)
    assert set(datos.rasgos) == {"local-rf"}  # sin embeddings todavía
    assert set(datos.bloques.tolist()) == set(bloques)
    assert set(np.unique(datos.clases).tolist()) == {0, 1}
    assert set(np.unique(datos.estratos).tolist()) <= {0, 1, 2}
    filas, preds = evaluar(exp, datos, _crear)
    assert np.nanmean([f["exactitud_balanceada"] for f in filas]) > 0.95
    texto, resultado = veredicto(exp, preds)
    assert resultado == {"faltan": ["galileo-r0-sonda"]}
