# E01. ¿Cuánto se degrada un modelo fundacional global en el trópico colombiano?

**Estado:** pre-registro. El brazo local corre; el brazo fundacional espera `cdcol embeber`
(fase 2). La fecha del commit que agrega este archivo es la fecha del pre-registro.

## Afirmación de la tesis que alimenta

Un modelo fundacional entrenado sobre todo con datos del norte global, usado tal cual (congelado),
rinde peor en condiciones tropicales colombianas que un modelo local entrenado con las mismas
etiquetas, y **la brecha crece con la nubosidad**. Si es cierto, adaptar al trópico (recetas r1+)
tiene sentido; si no, el resultado negativo también se publica: "para esta tarea, úsese el modelo
global".

## Hipótesis

- **H1 (degradación).** En el estrato *nublado*, la exactitud balanceada de la sonda lineal sobre
  Galileo congelado es menor que la del bosque aleatorio local sobre el ARD.
- **H2 (la nube la explica).** La brecha es más negativa en el estrato *nublado* que en el
  *despejado*.

## Diseño

| | |
|---|---|
| Zona y año | La Macarena, 2024, bloques fijados en `config.yaml` |
| Tarea | Bosque / no bosque, por píxel de 10 m |
| Referencia | MapBiomas Colombia reclasificado (ver "Limitaciones") |
| Píxeles elegibles | Ventana de 7 × 7 px con una sola clase en la referencia (lejos de bordes del mapa de 30 m) |
| Estratos | Terciles de observaciones S2 válidas en el año (`n_validas_s2` sumada): nublado, intermedio, despejado |
| Brazo local (`local-rf`) | Bosque aleatorio sobre mediana, p10 y p90 anuales de las 10 bandas S2 y VV/VH |
| Brazo fundacional (`galileo-r0-sonda`) | Regresión logística sobre embeddings de Galileo-tiny sin adaptar (receta `r0-base`) |
| Validación | 5 pliegues **por bloque**: entrenamiento y prueba nunca comparten bloque |
| Etiquetas | 10, 50, 100 y 500 por clase, del bloque de entrenamiento; 5 semillas |
| Prueba | Hasta 2000 píxeles por clase y estrato en los bloques de prueba |
| Métrica | Exactitud balanceada, por estrato |
| Incertidumbre | IC 95 % por bootstrap pareado (los dos brazos se evalúan en los mismos píxeles) que remuestrea **bloques**, no píxeles: los píxeles vecinos no son independientes |

Las capas de incertidumbre del cubo **no** entran como rasgos del brazo local: se usan para
estratificar. Si entraran, la comparación mezclaría dos cosas (cubo con incertidumbre vs. modelo
fundacional) y no se podría decir cuál explica la brecha. Eso es el experimento 2.

## Criterio de decisión (fijado antes de ver datos)

`brecha = exactitud(fundacional) − exactitud(local)`, con 100 etiquetas por clase, promediada
entre pliegues y semillas, δ = 0,02.

| Resultado en el estrato nublado | Conclusión |
|---|---|
| IC 95 % de la brecha entero por debajo de 0 | H1 apoyada: el modelo global se degrada |
| IC 95 % entero por encima de −δ | H1 refutada: el modelo global no pierde más de 2 puntos. Resultado negativo publicable |
| Otro | No concluyente: más bloques o más prueba, no cambiar el criterio |

H2: IC 95 % de `brecha(nublado) − brecha(despejado)` entero por debajo de 0.

## Correr

```bash
uv sync --extra cubo --extra bench
# 1. ARD de los 12 meses de los bloques del config
uv run cdcol ard-mes macarena 2024-01 --bloques x480_y182,...   # y así cada mes
# 2. la referencia en la ruta del config (ver abajo)
# 3. el experimento: corre los brazos que tengan datos y escribe resultados/
uv run cdcol experimento e01
```

Salida en `data/experimentos/e01/`: `resultados.csv` (una fila por brazo × pliegue × semilla ×
presupuesto × estrato) y `veredicto.md`.

## Pendiente antes de correrlo de verdad

1. **Fijar los bloques.** 10 a 20 bloques con bosque, borde agrícola y pasto.
2. **Referencia.** Bajar MapBiomas Colombia (colección que cubra 2024), recortarla a la zona y
   confirmar la reclasificación de `config.yaml` contra su leyenda.
3. **Puntos independientes.** MapBiomas es a su vez un modelo (Landsat, 30 m): sirve para
   entrenar y comparar brazos, pero no como verdad absoluta. Para la tesis hace falta una
   muestra fotointerpretada propia (p. ej. 300 puntos estratificados) y reportar ambas.
4. **Brazo fundacional.** Depende de `cdcol embeber` y del ADR del modelo base.

## Limitaciones conocidas

- La referencia a 30 m favorece rasgos que se parecen a Landsat; se mitiga con la ventana
  homogénea y con los puntos independientes.
- Un año y una zona: el resultado vale para bosque/no bosque en La Macarena, no para el trópico
  en general. E02 y E03 lo extienden (cultivos, otra zona).

## Cambios al pre-registro

Ninguno todavía.
