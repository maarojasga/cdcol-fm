# ADR 0005. Cálculo del ARD bajo demanda en AWS

**Estado:** aceptado (17-nov-2026). Reemplaza la idea de un catálogo STAC Browser con
almacenamiento permanente.

## Contexto

El ARD se calcula hoy en GitHub Actions. Eso tiene tres límites:
1. Los resultados viven 14 días como artefactos (deuda 2) y ya se perdieron meses.
2. Los términos de GitHub no permiten usar Actions como parte de un servicio para terceros.
3. No mide el costo de producir un dato, que es lo que pregunta H3 (costo en reposo frente a
   costo por uso).

Recursos: la cuenta de AWS de Ale con el crédito de bienvenida de 100 USD (Free Tier 2025). La
meta es que, si nadie pide nada, el gasto sea casi cero (ADR 0003).

## Decisión

**AWS Batch sobre Fargate Spot, en `us-west-2`, escribiendo a S3.** La infraestructura está en
`infra/aws/plantilla.yaml` (CloudFormation) y se maneja con `infra/aws/cdcol-aws.sh`.

| Pieza | Elección | Por qué |
|---|---|---|
| Región | `us-west-2` (Oregón) | Ahí están los COG de S2 de Earth Search: la lectura de S2, que es la mayor parte de los datos, se queda dentro de AWS |
| Cálculo | AWS Batch, un trabajo por zona × mes | Un mes tarda 1-2,5 h: no cabe en una petición web. Batch no cobra; sin trabajos en cola no hay nada encendido |
| Máquina | Fargate **Spot**, 4 vCPU / 16 GB, 100 GiB de disco | Lo mismo que el runner de Actions. Fargate da hasta 200 GiB de disco efímero: resuelve el riesgo de disco que tenía Cloud Run (allí `/tmp` ocupa RAM). Spot cuesta ~70 % menos; si se interrumpe, Batch reintenta una vez |
| Imagen | La misma `Dockerfile`, en ECR | Sin un segundo camino de código |
| Salida | `cdcol ard-mes ... --subir s3://<bucket>/zonas` | El comando sube la zona y deja `mediciones/<mes>.json` con tiempo, memoria y pico de disco (deuda 9, insumo de H3) |
| Almacenamiento | Bucket privado; `zonas/` expira a los 30 días, `permanente/` no expira | ADR 0003 para lo de trabajo; lo que respalda una publicación se copia a `permanente/` (deuda 2) |
| Llaves de CDSE | SSM Parameter Store (`/cdcol-fm/*`, SecureString) | Gratis y no quedan en la imagen ni en la plantilla |
| Red | VPC por defecto, IP pública, sin NAT | Un NAT Gateway cuesta ~32 USD/mes encendido; con IP pública solo se paga mientras corre la tarea |

**Frenos de gasto:**
- `MaxVcpus = 8`: como mucho dos meses calculándose a la vez. Es el freno duro.
- Presupuesto mensual (25 USD por defecto) con alertas por correo al 50 % y 80 % del gasto real y
  al 100 % del pronosticado. Mide el gasto **bruto** (`IncludeCredit: false`); si contara los
  créditos, se quedaría en cero y nunca avisaría.
- Registros con 30 días de retención e imágenes de ECR limitadas a las 3 últimas.

## Costo estimado (por confirmar con la primera corrida)

Con precios públicos de Fargate en EE. UU. (on-demand ~0,040 USD/vCPU-h y ~0,0044 USD/GB-h; Spot
~70 % menos), la tarea de 4 vCPU / 16 GB cuesta ~0,23 USD/h on-demand o ~0,07 USD/h en Spot.

| Qué | Spot | On-demand |
|---|---|---|
| Un mes de La Macarena (~2,5 h) | ~0,20 USD | ~0,60 USD |
| Los 12 meses del E01 | ~2,5 USD | ~7 USD |
| En reposo (S3 + ECR, sin trabajos) | céntimos al mes | |

El cálculo grueso anterior (1 USD por bloque y mes) estaba muy por encima: el comando calcula todos
los bloques de una zona en la misma tarea. La primera corrida (`cdcol-aws.sh probar`) da el número
real de tiempo y disco, y la factura de ese día, el costo.

## Lo que queda fuera de este ADR

- **La página con el mapa y el servicio que lanza trabajos** para otras personas. Requiere inicio
  de sesión o una lista de correos, cuotas por pedido y por día, y aviso por correo al terminar.
  Va en otro ADR cuando el cálculo esté medido.
- **El visor leyendo de S3** (deuda 11).
- **Los embeddings** (`cdcol embeber`): Galileo-tiny en CPU debería caber en la misma definición
  de trabajo; se confirma en la prueba de factibilidad.

## Riesgos

1. **Plan gratuito de AWS.** Las cuentas nuevas en el plan gratuito no tienen acceso a algunos
   servicios. AWS Batch está en la lista de servicios incluidos; Fargate no se pudo confirmar. Si
   la cuenta lo bloquea, se pasa al plan de pago: el crédito restante se sigue aplicando.
2. **CDSE.** Todos los trabajos usan las llaves de Ale, y CDSE limita las descargas simultáneas.
   Con `MaxVcpus = 8` hay como mucho dos trabajos a la vez.
3. **Interrupciones de Spot.** Un trabajo interrumpido vuelve a empezar el mes desde cero. Si pasa
   seguido, se cambia el entorno a `FARGATE` (on-demand), que cuesta ~3 veces más.
4. **Vencimiento del crédito.** El crédito del plan gratuito vence (6 o 12 meses, según la
   página de AWS que se lea). Hay que revisar la fecha en la consola de facturación.

## Fuentes

- [AWS Free Tier: crédito de 200 USD y plan gratuito de 6 meses (jul-2025)](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan)
- [Preguntas frecuentes del Free Tier](https://aws.amazon.com/free/faqs/)
- [Planes del Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html)
- [Precios de Fargate](https://aws.amazon.com/fargate/pricing/) y [de AWS Batch](https://aws.amazon.com/batch/pricing)
