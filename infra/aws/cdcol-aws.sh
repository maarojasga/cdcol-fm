#!/usr/bin/env bash
# Despliegue y uso de cdcol-fm en AWS (ADR 0005). Necesita AWS CLI v2 con credenciales
# (`aws configure`) y Docker. En Windows corre en Git Bash.
#
#   infra/aws/cdcol-aws.sh pila tu@correo.com    # crea o actualiza bucket, Batch y presupuesto
#   infra/aws/cdcol-aws.sh llaves                # sube las llaves de CDSE de .env a SSM
#   infra/aws/cdcol-aws.sh imagen                # construye y sube la imagen Docker a ECR
#   infra/aws/cdcol-aws.sh probar                # 1 bloque × 1 mes, para medir disco y costo
#   infra/aws/cdcol-aws.sh lanzar ZONA MES [BLOQUES]
#   infra/aws/cdcol-aws.sh estado                # últimos trabajos
#   infra/aws/cdcol-aws.sh medicion ZONA MES     # tiempo, memoria y disco de esa corrida
set -euo pipefail

export AWS_REGION="${AWS_REGION:-us-west-2}"  # donde están los COG de S2 de Earth Search
PILA=cdcol-fm
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"

salida() {  # valor de una salida de la pila
  aws cloudformation describe-stacks --stack-name "$PILA" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

case "${1:-}" in
  pila)
    correo="${2:?uso: pila CORREO [PRESUPUESTO_USD]}"
    vpc=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
      --query 'Vpcs[0].VpcId' --output text)
    [ "$vpc" = "None" ] && { echo "No hay VPC por defecto en $AWS_REGION" >&2; exit 1; }
    subredes=$(aws ec2 describe-subnets \
      --filters Name=vpc-id,Values="$vpc" Name=default-for-az,Values=true \
      --query 'Subnets[].SubnetId' --output text | tr '\t' ',')
    aws cloudformation deploy --stack-name "$PILA" \
      --template-file "$RAIZ/infra/aws/plantilla.yaml" \
      --capabilities CAPABILITY_IAM \
      --parameter-overrides CorreoAlertas="$correo" PresupuestoUSD="${3:-25}" \
        VpcId="$vpc" Subredes="$subredes"
    aws cloudformation describe-stacks --stack-name "$PILA" \
      --query 'Stacks[0].Outputs' --output table
    echo "Revisa $correo: AWS pide confirmar la suscripción a las alertas."
    ;;

  llaves)
    # SSM Parameter Store estándar es gratis y cifra con la llave de AWS por defecto
    set -a; . "$RAIZ/.env"; set +a
    for par in "cdse-access-key:CDSE_S3_ACCESS_KEY" "cdse-secret-key:CDSE_S3_SECRET_KEY"; do
      nombre="${par%%:*}"; var="${par#*:}"
      valor=$(printf %s "${!var:-}" | tr -d '\r')  # .env guardado en Windows trae CRLF
      [ -n "$valor" ] || { echo "falta $var en .env" >&2; exit 1; }
      aws ssm put-parameter --name "/cdcol-fm/$nombre" --type SecureString --overwrite \
        --value "$valor" >/dev/null
      echo "/cdcol-fm/$nombre listo"
    done
    ;;

  imagen)
    uri=$(salida Imagen)
    aws ecr get-login-password | docker login --username AWS --password-stdin "${uri%%/*}"
    # Fargate corre x86_64; --platform evita una imagen ARM si se construye en un Mac M
    docker build --platform linux/amd64 -t "$uri:latest" -t "$uri:$(git -C "$RAIZ" rev-parse --short HEAD)" "$RAIZ"
    docker push --all-tags "$uri"
    ;;

  lanzar|probar)
    if [ "$1" = probar ]; then zona=macarena; mes=2024-01; bloques=x479_y182
    else zona="${2:?uso: lanzar ZONA MES [BLOQUES]}"; mes="${3:?falta MES}"; bloques="${4:-todos}"; fi
    aws batch submit-job --job-name "ard-$zona-$mes" \
      --job-queue "$(salida Cola)" --job-definition cdcol-ard-mes \
      --parameters "zona=$zona,mes=$mes,bloques=$bloques" \
      --query jobId --output text
    echo "Sigue el avance con: $0 estado"
    ;;

  estado)
    for s in RUNNABLE STARTING RUNNING SUCCEEDED FAILED; do
      aws batch list-jobs --job-queue cdcol-fm --job-status "$s" \
        --query "jobSummaryList[:5].[jobName,status,statusReason]" --output text
    done
    echo "Registros: aws logs tail /cdcol-fm/batch --follow"
    ;;

  medicion)
    zona="${2:?uso: medicion ZONA MES}"; mes="${3:?falta MES}"
    aws s3 cp "s3://$(salida Bucket)/zonas/$zona/mediciones/$mes.json" -
    ;;

  *)
    sed -n '2,13p' "$0"; exit 1 ;;
esac
