# cdcol-fm

Open Data Cube con modelos fundacionales para Latinoamérica, con Colombia como caso.

Es la continuación de CDCol (Uniandes + IDEAM, 2016-2021), uno de los primeros cubos nacionales de datos del mundo. CDCol demostró que un cubo nacional era posible y dejó documentado por qué no se sostuvo. Este repositorio retoma esa idea con tres cambios:

1. **Una capa de embeddings de modelos fundacionales** (Sentinel-1 + Sentinel-2, adaptados al trópico) en vez de un algoritmo por tarea.
2. **La incertidumbre y la densidad de observación como bandas de primera clase** del cubo, no como un apéndice.
3. **El linaje viaja con el dato** (STAC), y casi no hay infraestructura que mantener, para que el cubo sobreviva a su financiación.

## Estado

Fase 1: el cubo ARD mensual (Sentinel-2 + Sentinel-1 con corrección de relieve propia y capas de
incertidumbre) ya corre de punta a punta. La zona piloto es La Macarena.

## Correr en tu computador

Hay dos caminos. Ninguno necesita nube: los datos se bajan gratis de Earth Search, Planetary
Computer y Copernicus, y los productos quedan en la carpeta `data/`.

**1. Con Docker** (no hay que instalar Python; sirve en Windows, Mac y Linux):

```bash
git clone https://github.com/maarojasga/cdcol-fm.git && cd cdcol-fm
cp .env.ejemplo .env          # y pon ahí tus llaves de Copernicus (ver abajo)
docker compose run --rm cdcol ard prueba --s1 cdse    # zona de prueba: ~5 min
docker compose run --rm cdcol vista prueba            # escribe la página para verla
```

Luego abre `data/prueba/vista/index.html` con doble clic.

**2. Con uv** (si ya trabajas con Python):

```bash
uv sync --extra cubo --extra radar
export CDSE_S3_ACCESS_KEY=...  CDSE_S3_SECRET_KEY=...
uv run cdcol ard prueba --s1 cdse
uv run cdcol vista prueba                             # abre el navegador
```

### Qué deberías ver

La página tiene un botón por mes y uno por capa:

| Capa | Qué es | Qué esperar |
|---|---|---|
| Color natural | Mediana del mes de Sentinel-2, sin nubes | Paisaje reconocible; manchas negras donde no hubo ni una vista clara |
| Falso color | Infrarrojo, rojo, verde | Bosque y cultivos en rojo, suelo y pasto seco en verde-café |
| Radar VV / VH | Sentinel-1 corregido por relieve | Imagen completa aunque haya nubes; laderas sin rayas por el relieve |
| Observaciones válidas | Fechas sin nube por píxel | Pocas en meses lluviosos (febrero-marzo en el piloto) |
| Nube | % de observaciones nubladas | Alto donde el óptico es poco confiable |
| Días desde vista clara | Antigüedad del último dato limpio | Crece en temporada de lluvias |

Cada mes también trae un `item.json` (STAC) con las escenas que usó, para reconstruirlo.

### Zonas grandes

Una zona grande se parte en bloques de 10 km y se calcula mes a mes; cada escena de radar se baja
y se corrige una sola vez para toda la zona:

```bash
uv run cdcol bloques macarena                                  # 105 bloques
uv run cdcol ard-mes macarena 2024-01                          # un mes, todos los bloques (~3 h)
uv run cdcol ard-mes macarena 2024-01 --bloques x480_y182      # un mes, un bloque
uv run cdcol vista macarena                                    # mosaico de los bloques
```

Los mismos comandos funcionan con `docker compose run --rm cdcol ...`.

Para desarrollar: `uv sync --extra cubo --extra radar`, `make test` y `make lint`.

## Estructura

| Carpeta | Qué hay |
|---|---|
| `config/` | Países, zonas, productos ODC, recetas de adaptación y manifiestos. Lo único que se conserva de una zona archivada. |
| `src/cdcol_fm/` | El paquete. Un módulo por componente del plan. |
| `docs/adr/` | Decisiones de arquitectura. |
| `infra/` | Cubo local para desarrollo. |
| `experimentos/` | Un directorio por experimento de la tesis. |

## Credenciales de Copernicus

El radar (Sentinel-1 GRD) se baja de Copernicus Data Space con llaves S3 gratuitas, que se generan en
https://eodata-s3keysmanager.dataspace.copernicus.eu/panel/s3-credentials ("Add credential"). Van en
el archivo `.env` (que nunca se sube a git), como variables de entorno o como secretos del
repositorio; nunca en la config. Sin llaves, `--s1 pc` usa el radar ya corregido de Planetary
Computer, que trae menos fechas.

## Ciclo de vida de una zona

Los datos de una zona existen solo mientras un proyecto la usa. `cdcol archivar <zona>` borra los productos y deja en git la configuración y un manifiesto con lo que realmente se usó, y `cdcol reconstruir <zona>` lo rehace. Ver [ADR 0003](docs/adr/0003-ciclo-de-vida-de-zonas.md).

## Licencias

Código: Apache-2.0. Datos y benchmark publicados: CC BY 4.0.
