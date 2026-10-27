# ADR 0004. Modelo base de la capa de embeddings

**Estado:** propuesta (27-oct-2026). Decide Ale.

## Contexto

La capa de embeddings (fase 2) necesita un modelo base preentrenado que reciba lo que produce el cubo:
compuestos **mensuales** de Sentinel-2 (10 bandas, reflectancia) y Sentinel-1 (VV, VH en dB,
corregidos por relieve), en la grilla nacional a 10 m. El E01 lo usa congelado (receta `r0-base`)
y las recetas r1+ lo adaptan al trópico, así que los pesos tienen que poder descargarse y ajustarse.

Requisitos, en orden:
1. Acepta S1 **y** S2 a la vez.
2. Acepta series de tiempo (el cubo es mensual).
3. Pesos y código abiertos, con licencia que permita adaptarlos y publicar los resultados.
4. Corre la inferencia sin GPU dedicada para 15 bloques (o con GPU gratuita).
5. Se integra sin forks (ADR 0002): un producto `emb_<modelo>_<receta>_<versión>` por modelo.

## Opciones

| Modelo | S1+S2 | Tiempo | Licencia | Tamaños | Lo que lo descarta o lo favorece |
|---|---|---|---|---|---|
| **Galileo** (NASA Harvest, ICML 2025) | Sí | Sí: hasta 24 pasos con su mes; preentrenado con 12 mensuales | MIT (código) | nano (dim 128, 4 capas), tiny (192, 12), base (768, 12) | Mismas 10 bandas S2 que el cubo; S1 en dB. Recibe además DEM y otras capas, que se pueden enmascarar |
| **TerraMind** (IBM + ESA, 2025) | Sí, y tiene modalidad **S1 RTC** | No: una fecha por muestra | Apache-2.0 | tiny, small, base, large | Integrado en TerraTorch (ya está en el extra `modelos`). Habría que embeber mes a mes y agregar |
| **Clay v1.5** | Sí, varios sensores | No: una fecha | Apache-2.0 (código y pesos) | uno | Flexible en sensores, pero sin dimensión temporal |
| **Prithvi-EO-2.0** (NASA + IBM) | No: solo HLS (6 bandas, 30 m) | Sí | — | 300M, 600M | Sin radar y a 30 m: no sirve para la tesis |
| **AlphaEarth** (Google DeepMind) | Sí (internamente) | Anual | Embeddings CC-BY 4.0; **el modelo no se publica** | — | No se puede adaptar ni correr sobre nuestro ARD. Útil como referencia externa, no como modelo base |

## Decisión propuesta

**Galileo como modelo base**, con **tiny** para `r0-base` (lo que ya fija el E01) y **base** para las
recetas de adaptación si tiny se queda corto.

- Es el único que cumple 1 y 2 a la vez: recibe la serie mensual S1+S2 tal como la produce el cubo,
  con las mismas 10 bandas de S2 y S1 en dB. Las capas de incertidumbre no entran al modelo (E01).
- MIT permite adaptar y publicar.
- tiny (~5 M parámetros, estimado de su config) debería correr en CPU para 15 bloques; se mide
  antes de comprometerse.

**TerraMind como alternativa**, no en paralelo: si Galileo falla en algo de lo que queda por
verificar, es el siguiente candidato (Apache-2.0, S1 RTC nativo, TerraTorch). Compararlos los dos
sería otro experimento, no parte del E01.

**AlphaEarth como posible tercer brazo del E01**, porque es lo que un usuario usaría "listo para
usar" sin cubo. Agregarlo es un cambio al pre-registro: se decide y anota **antes** de correr el
E01, o se deja para un E01b.

## Riesgos y lo que falta verificar

1. **Distinto radar.** Galileo se preentrenó con `COPERNICUS/S1_GRD` de Earth Engine: sigma0 en dB,
   ortorrectificado pero **sin** aplanamiento radiométrico del relieve. El cubo produce gamma0 con
   aplanamiento (RTC). En terreno plano la diferencia es pequeña; en la serranía no. Opciones:
   (a) usar gamma0 y medirlo como parte de la degradación; (b) producir también sigma0 sin
   aplanar para el modelo (sarsen lo hace con `correct_radiometry=None`); (c) que lo absorba la
   adaptación r1. Propuesta: (a) para r0, y registrar en el E01 que es una diferencia de entrada.
2. **Distinto compuesto óptico.** Galileo usó mosaicos sin nubes de Earth Engine
   (`S2_SR_HARMONIZED`); el cubo usa la mediana de observaciones válidas de Earth Search C1. Hay que
   confirmar que ambos dan reflectancia × 10⁴ sin el desfase de 1000 de las baselines nuevas.
3. **Geografía del preentrenamiento.** Falta leer en el artículo cómo se muestreó el mundo y
   cuánto trópico vio. Es dato de la tesis (el 4 % de Sudamérica que motivó todo).
4. **Licencia de los pesos.** El repositorio es MIT; falta confirmar que los pesos en Hugging Face
   (`nasaharvest/galileo`) tienen la misma.
5. **Resolución de los embeddings.** Galileo produce un vector por parche (1 a 8 px); para
   clasificar píxeles de 10 m hay que elegir el tamaño de parche y medir costo. Se decide al
   implementar `cdcol embeber`, con una medición en un bloque.

## Consecuencias

- `config/recetas/r0-base.yaml` fija `modelo_base: galileo-tiny` y, al bajar los pesos, su sha256.
- `cdcol embeber` implementa `Encoder` (`embeddings/interfaz.py`) para Galileo y escribe el producto
  `emb_galileo-tiny_r0-base_v0`.
- Si se cambia de modelo, es otro producto (ADR 0002), no una migración.

## Fuentes

- Galileo: [repositorio](https://github.com/nasaharvest/galileo) (licencia, `config/models/*.json`,
  `src/data/earthengine/s1.py` y `s2.py`, revisados el 27-oct-2026) y
  [arXiv:2502.09356](https://arxiv.org/abs/2502.09356v3).
- TerraMind: [arXiv:2504.11171](https://arxiv.org/pdf/2504.11171),
  [ficha en Hugging Face](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-base),
  [ESA](https://www.esa.int/Applications/Observing_the_Earth/ESA_and_IBM_collaborate_on_TerraMind).
- Prithvi-EO-2.0: [arXiv:2412.02732](https://arxiv.org/html/2412.02732v1).
- Clay: [documentación](https://clay-foundation.github.io/model), embeddings v1.5 en el
  [registro de AWS](https://registry.opendata.aws/lgnd-clay-v1-5-sentinel2/).
- AlphaEarth: [Satellite Embedding en Earth Engine](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL),
  [registro de AWS](https://registry.opendata.aws/aef-source/).

Las fichas de TerraMind y Clay no se pudieron abrir desde el entorno de desarrollo; sus licencias y
modalidades salen de búsquedas y hay que confirmarlas en la fuente antes de citarlas.
