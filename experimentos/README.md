# Experimentos de la tesis

Un directorio por experimento, con su config y un README que diga qué afirmación de la tesis
alimenta, cuál es el criterio de decisión (fijado antes de ver datos) y qué resultado la refutaría.

**Regla:** un experimento pre-registrado no cambia de tarea, zona ni criterio después de ver datos.
Para crecer se agrega un experimento nuevo, con su propio pre-registro. Cada uno se sostiene solo.

| Id | Pregunta | Estado |
|---|---|---|
| [e01](e01-degradacion-tropical/) | ¿Cuánto se degrada un modelo fundacional global en el trópico colombiano, y crece con la nube? Bosque / no bosque, La Macarena | Pre-registro; brazo local listo |

## Ruta de crecimiento (propuesta, sin pre-registrar)

De la tarea más fácil de referenciar a la que más importa para el caso de crédito. Cada paso se
pre-registra solo cuando su referencia esté conseguida.

| Paso | Tarea | Zona | Por qué en este orden | Referencia por conseguir |
|---|---|---|---|---|
| E02 | Coberturas en varias clases (bosque, pasto, cultivo, agua) | La Macarena | Misma zona y ARD que E01; prueba si la brecha cambia con una tarea más fina | MapBiomas Colombia, todas las clases |
| E03 | Cultivo de arroz / no arroz | `meta-arroz` | Primer cultivo; zona más cercana al crédito agrícola | UPRA o fotointerpretación propia (licencia por confirmar) |
| E04 | Cultivos de minifundio (café, plátano, pasto) | `eje-cafetero` | Predios < 5 ha y terreno andino: el caso más difícil | Fotointerpretación propia o datos de una entidad financiera |
