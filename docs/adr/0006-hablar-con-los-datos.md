# ADR 0006. Página para hablar con los datos

**Estado:** propuesto (18-nov-2026). La parte local está probada; el despliegue en AWS está
escrito y falta correrlo y medirlo.

## Contexto

El ARD ya se calcula bajo demanda en AWS (ADR 0005), pero solo se mira con `cdcol vista` (archivos
locales) o leyendo números a mano. La primera versión de la página debe dejar que una persona del
grupo elija una zona y le pregunte a los datos en lenguaje natural ("¿qué mes fue el más
nublado?", "¿cómo cambió el NDVI entre enero y julio?").

Decisiones tomadas con Ale (18-nov-2026):
1. **Usuarios:** Ale y su grupo, con lista de correos autorizados. No es pública.
2. **Nube:** AWS, junto al bucket (`us-west-2`): una cuenta, una factura y los datos no salen.
3. **Modelo:** Claude por la API de Anthropic (`claude-opus-5-5`), con su propia llave.

## Decisión

**El modelo no ve píxeles: llama herramientas que leen los COG y le devuelven números.** La
respuesta muestra qué herramientas se llamaron, con qué entrada y qué devolvieron, para que se
pueda revisar de dónde sale cada cifra.

| Pieza | Elección | Por qué |
|---|---|---|
| Herramientas | `resumen_zona`, `estadistica`, `calidad`, `comparar`, `mapa` (`src/cdcol_fm/chat/herramientas.py`) | Cubren niveles, series, confiabilidad, cambios e imágenes. Pocas y con esquema cerrado: menos llamadas erradas |
| Datos | Lectura directa de los COG, local o `s3://` (`chat/datos.py`) | Sin base de datos ni índice (ADR 0001); un COG de un bloque pesa 1-2 MB |
| Área | Bloques enteros de la grilla nacional, elegidos con clic | Sin recortes por polígono en la v1: más simple y sin ambigüedad sobre qué píxeles entran |
| Calidad | La herramienta `calidad` y el prompt obligan a revisar la nube antes de concluir con ópticos | Es el aporte del cubo: decir cuándo el dato no es confiable |
| Bucle | Manual, historial solo agregado al final, `fallbacks: "default"`, esfuerzo `medium` (`chat/agente.py`) | Control de cada llamada para mostrarla; caché del prompt; el modelo rechaza historiales editados |
| Página | HTML + JS sin compilación, MapLibre 4.7.1 (`web/`) | Igual que `vista`: se sirve como archivos estáticos |
| Local | `cdcol web --datos data` (o `s3://<bucket>/zonas`) | Probar todo antes de desplegar |

**Fuera de la v1:** pedir cálculos nuevos desde la página (Batch con cuotas, siguiente versión);
responder "cuánto bosque hay" con rigor (necesita el clasificador del E01); polígonos libres.

## Despliegue en AWS

Pila aparte, `cdcol-fm-web` (`infra/aws/web.yaml`), con `infra/aws/cdcol-aws.sh web`. Se puede
borrar sin tocar el cálculo.

| Pieza | Elección | Por qué |
|---|---|---|
| Página | `web/` en un bucket privado detrás de CloudFront (OAC) | Estática; `config.js` la genera el despliegue con la URL de la API y Cognito |
| API | El mismo `cdcol web` en Lambda con el adaptador web de Lambda 1.1.0 (`infra/aws/web.Dockerfile`, solo el extra `chat`) | Un solo código en local y en AWS. Imagen de 1,2 GB, probada con disco de solo lectura |
| Entrada a la API | URL de función, llamada directo desde el navegador (CORS al dominio de CloudFront) | API Gateway y CloudFront cortan a los 30-60 s; una pregunta puede tardar más. Desde oct-2025 la URL pública necesita los permisos `InvokeFunctionUrl` e `InvokeFunction` |
| Inicio de sesión | Cognito (plan Lite, pantalla clásica), solo usuarios creados con `cdcol-aws.sh usuario` = la lista de correos. La página usa el flujo de código con PKCE | La API valida el token con `GetUser` (Cognito revisa firma, vencimiento y revocación; sin dependencias nuevas). Exige el alcance `aws.cognito.signin.user.admin` |
| Estado | En el bucket de datos: `conversaciones/` (30 días), `imagenes/` (7, se sirven con URL firmada) y `cuotas/` (7) | Cada petición puede caer en otra instancia de Lambda. Las conversaciones se guardan con los bloques tal cual vuelven de la API |
| Llave de Anthropic | SSM `/cdcol-fm/anthropic-api-key`, leída al arrancar | Como las de CDSE; no queda en la imagen |
| Frenos | 40 preguntas por persona y día (`CuotaDiaria`), un límite de gasto en la consola de Anthropic y el presupuesto de AWS del ADR 0005 | La cuota se cuenta en S3 sin atomicidad: basta para un grupo pequeño |

## Riesgos

1. **Costo por pregunta.** Cada pregunta son varias llamadas al modelo. Hay que medirlo con uso
   real (la API devuelve los tokens; la página ya los recibe en `uso`) antes de abrirla al grupo.
2. **Respuestas plausibles pero equivocadas.** Se mitiga con números solo de herramientas y
   mostrando las consultas; no se elimina. Conviene un conjunto de preguntas con respuesta conocida
   para revisarlo cuando cambie el prompt o el modelo.
3. **Lectura desde S3 en Lambda.** Cada pregunta puede leer decenas de COG; la caché en memoria
   solo dura lo que dure la instancia. Medir latencia con 15 bloques × 12 meses.
4. **Mapa base.** Las teselas de OpenStreetMap tienen política de uso justo; para más usuarios
   habría que usar un proveedor con cuenta.
