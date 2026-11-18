# ADR 0001. STAC es la fuente de verdad; el índice de ODC es un caché

**Estado:** aceptada (fase 0).

## Contexto
En CDCol el linaje vivía en la base de datos del portal y se perdió cuando se apagó. Diez años después, esa base de datos no existe y no hay forma de saber con qué versión se calculó un producto.

## Decisión
- Cada producto derivado es un archivo (COG) más un ítem STAC que lleva su linaje completo: ítems fuente, modelo base y sha256 de pesos, receta y su hash, versión de los datos y commit del repositorio.
- El índice de Open Data Cube (Postgres/PostGIS) se trata como caché. Si se pierde, se reconstruye desde el catálogo STAC con `stac-to-dc`.
- Las capas de incertidumbre son bandas del mismo producto ARD, en la misma grilla. No son un producto aparte.
- Los datos nunca van a git; solo la configuración y los manifiestos.

## Consecuencias
- No hay portal ni servidor que mantener para conservar el linaje.
- Cualquier herramienta que entienda STAC puede leer el cubo sin ODC.
