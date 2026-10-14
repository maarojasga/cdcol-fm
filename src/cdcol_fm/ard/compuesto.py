"""Compuesto mensual S1+S2 con capas de incertidumbre por píxel.

Funciones puras sobre xarray: no saben de dónde vienen los datos, así se prueban sin red.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from cdcol_fm.ard.bandas import BANDAS_S2
from cdcol_fm.ard.mascara import nube, observada, validas

SIN_VISTA_CLARA = np.uint16(65535)
FRECUENCIA = "1MS"  # mensual, etiquetado al inicio del mes


def _fin_de_mes(tiempos: xr.DataArray) -> np.ndarray:
    inicio = tiempos.values.astype("datetime64[M]")
    return (inicio + np.timedelta64(1, "M")).astype("datetime64[ns]")


def compuesto_s2(s2: xr.Dataset) -> xr.Dataset:
    """``s2`` con dims (time, y, x), bandas BANDAS_S2 (reflectancia) y ``SCL``."""
    ok = validas(s2["SCL"])
    limpio = s2[list(BANDAS_S2)].where(ok)
    por_mes = limpio.resample(time=FRECUENCIA)

    salida = por_mes.median(skipna=True)
    n_validas = ok.resample(time=FRECUENCIA).sum().astype("uint8")
    # dispersión media entre bandas; NaN con menos de 2 observaciones válidas
    desv = por_mes.std(skipna=True, ddof=1).to_array("banda").mean("banda")
    salida["incert_s2"] = desv.where(n_validas >= 2).astype("float32")
    salida["n_validas_s2"] = n_validas

    obs = observada(s2["SCL"]).resample(time=FRECUENCIA).sum()
    con_nube = nube(s2["SCL"]).resample(time=FRECUENCIA).sum()
    frac = (100 * con_nube / obs.where(obs > 0)).fillna(255)
    salida["prob_nube"] = frac.round().astype("uint8")

    salida["dias_desde_clara"] = _dias_desde_clara(ok, salida["time"])
    return salida


def _dias_desde_clara(ok: xr.DataArray, meses: xr.DataArray) -> xr.DataArray:
    """Días entre el fin de cada mes y la última observación válida anterior (de cualquier mes)."""
    t = ok["time"].values.astype("datetime64[ns]")
    ultima = np.full(ok.shape[1:], np.datetime64("NaT", "ns"))
    orden = np.argsort(t)
    fines = _fin_de_mes(meses)
    capas = []
    i = 0
    for fin in fines:
        while i < len(orden) and t[orden[i]] < fin:
            k = orden[i]
            ultima = np.where(ok.values[k], t[k], ultima)
            i += 1
        dias = (fin - ultima) / np.timedelta64(1, "D")
        capa = np.where(np.isnat(ultima), SIN_VISTA_CLARA, np.minimum(dias, 65534))
        capas.append(capa.astype("uint16"))
    return xr.DataArray(
        np.stack(capas),
        coords={"time": meses, **{d: ok[d] for d in ok.dims[1:]}},
        dims=("time", *ok.dims[1:]),
    )


def compuesto_s1(s1: xr.Dataset) -> xr.Dataset:
    """``s1`` con ``VV`` y ``VH`` en potencia lineal (RTC gamma0). Mediana mensual en dB."""
    lin = s1[["VV", "VH"]].where(s1[["VV", "VH"]] > 0)
    med = lin.resample(time=FRECUENCIA).median(skipna=True)
    salida: xr.Dataset = (10 * np.log10(med)).astype("float32")  # type: ignore[assignment]
    salida["n_adq_s1"] = lin["VV"].notnull().resample(time=FRECUENCIA).sum().astype("uint8")
    return salida


def compuesto_mensual(s2: xr.Dataset, s1: xr.Dataset | None) -> xr.Dataset:
    """Producto ``ard_s1s2_mensual``. Sin S1 en un mes, VV/VH quedan NaN y n_adq_s1 en 0."""
    from cdcol_fm.ard.bandas import BANDAS_ARD

    salida = compuesto_s2(s2)
    if s1 is not None and s1.sizes.get("time", 0) > 0:
        radar = compuesto_s1(s1).reindex(time=salida["time"])
        radar["n_adq_s1"] = radar["n_adq_s1"].fillna(0).astype("uint8")
        salida = salida.merge(radar)
    else:
        forma = salida["n_validas_s2"]
        salida["VV"] = xr.full_like(forma, np.nan, dtype="float32")
        salida["VH"] = xr.full_like(forma, np.nan, dtype="float32")
        salida["n_adq_s1"] = xr.zeros_like(forma, dtype="uint8")
    return salida[list(BANDAS_ARD)]
