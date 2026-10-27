"""Bandas del producto ``ard_s1s2_mensual``.

Las capas de incertidumbre son bandas del mismo producto, en la misma grilla.
"""

BANDAS_S2 = ("B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12")
BANDAS_S1 = ("VV", "VH")
BANDAS_INCERTIDUMBRE = (
    "n_validas_s2",  # observaciones ópticas válidas en el mes
    "dias_desde_clara",  # días desde la última observación óptica limpia
    "prob_nube",  # % de observaciones del mes marcadas como nube
    "n_adq_s1",  # adquisiciones S1 del mes
    "incert_s2",  # dispersión de las observaciones válidas
)
BANDAS_ARD = BANDAS_S2 + BANDAS_S1 + BANDAS_INCERTIDUMBRE
