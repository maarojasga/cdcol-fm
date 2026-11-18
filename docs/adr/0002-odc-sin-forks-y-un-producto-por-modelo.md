# ADR 0002. ODC upstream sin forks; un producto de embeddings por modelo y receta

**Estado:** aceptada (fase 0).

## Contexto
La modernización cloud-native de ODC (`odc-stac`, `odc-geo`, `odc-loader`, driver PostGIS de `datacube` 1.9) la está haciendo la comunidad. Competir ahí sería plomería que se queda vieja rápido. El núcleo heredado de CDCol envejeció justamente por eso.

Los modelos base (Galileo, TerraMind, ...) cambian cada año, y sus embeddings viven en espacios distintos.

## Decisión
- Usar `datacube-core`, `odc-stac`, `odc-geo`, `odc-loader` y `odc-apps-dc-tools` tal como vienen, con versiones fijadas en `uv.lock`.
- Cada combinación modelo base × receta × versión es su propio producto ODC: `emb_<modelo>_<receta>_<versión>` (ver `cdcol_fm.embeddings.interfaz.nombre_producto`).
- Embeddings de productos distintos nunca se mezclan ni se comparan entre sí directamente.
- Formato: COG con una banda por dimensión, como publica AlphaEarth.

## Consecuencias
- Cambiar de modelo base es agregar un producto, no migrar uno.
- Lo propio del repositorio es la receta, el modelo de datos de incertidumbre y el benchmark, no el motor del cubo.
