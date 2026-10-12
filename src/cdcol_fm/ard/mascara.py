"""Máscara de observaciones válidas a partir de la SCL de Sentinel-2 L2A.

Criterio conservador: solo cuenta como válido lo que la SCL clasifica como superficie.
Inferido, a medir en las zonas piloto: la SCL subestima la nube en el trópico.
"""

from __future__ import annotations

import xarray as xr

# 4 vegetación, 5 suelo desnudo, 6 agua, 7 sin clasificar, 11 nieve
SCL_VALIDAS = (4, 5, 6, 7, 11)
# 8 nube media, 9 nube alta, 10 cirro
SCL_NUBE = (8, 9, 10)
# 0 sin dato
SCL_SIN_DATO = 0


def validas(scl: xr.DataArray) -> xr.DataArray:
    return scl.isin(SCL_VALIDAS)


def observada(scl: xr.DataArray) -> xr.DataArray:
    """El satélite pasó y hay dato (válido o no)."""
    return scl != SCL_SIN_DATO


def nube(scl: xr.DataArray) -> xr.DataArray:
    return scl.isin(SCL_NUBE)
