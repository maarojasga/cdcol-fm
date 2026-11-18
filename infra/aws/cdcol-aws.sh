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
#   infra/aws/cdcol-aws.sh registros             # registros de los trabajos, en vivo
# Página del chat (ADR 0006), en la pila cdcol-fm-web:
#   infra/aws/cdcol-aws.sh web-llave             # sube ANTHROPIC_API_KEY de .env a SSM
#   infra/aws/cdcol-aws.sh web                   # despliega o actualiza todo (pila, imagen, página)
#   infra/aws/cdcol-aws.sh web-publicar          # solo vuelve a subir web/
#   infra/aws/cdcol-aws.sh usuario CORREO        # da acceso (le llega una contraseña temporal)
#   infra/aws/cdcol-aws.sh web-registros         # registros de la API, en vivo
set -euo pipefail

export AWS_REGION="${AWS_REGION:-us-west-2}"  # donde están los COG de S2 de Earth Search
# Git Bash convierte los argumentos que empiezan con / en rutas de Windows; los nombres de SSM y
# de los grupos de registros empiezan con /cdcol-fm o /aws/lambda y deben llegar tal cual
export MSYS2_ARG_CONV_EXCL="/cdcol-fm;/aws/lambda${MSYS2_ARG_CONV_EXCL:+;$MSYS2_ARG_CONV_EXCL}"
PILA=cdcol-fm
PILA_WEB=cdcol-fm-web
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"

salida() {  # valor de una salida de la pila (la principal o la que se indique)
  aws cloudformation describe-stacks --stack-name "${2:-$PILA}" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

commit_actual() {
  # el commit queda en el linaje de cada ítem (la imagen no trae .git); con cambios sin
  # commit se marca, porque el código de la imagen ya no es exactamente ese commit
  local c
  c=$(git -C "$RAIZ" rev-parse HEAD)
  git -C "$RAIZ" diff --quiet HEAD -- src config web Dockerfile infra/aws pyproject.toml uv.lock \
    || c="$c-modificado"
  echo "$c"
}

desplegar_web() {  # $1 = URI@digest de la imagen, o vacío si aún no hay
  aws cloudformation deploy --stack-name "$PILA_WEB" \
    --template-file "$RAIZ/infra/aws/web.yaml" \
    --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
    --parameter-overrides BucketDatos="$(salida Bucket)" ImagenWeb="$1" \
      CuotaDiaria="${CUOTA_DIARIA:-40}"
}

publicar_web() {
  local bucket api config
  bucket=$(salida BucketWeb "$PILA_WEB")
  api=$(salida Api "$PILA_WEB")
  config=$(mktemp)
  cat > "$config" <<EOF
// Generado por cdcol-aws.sh web-publicar: no editar a mano.
window.CDCOL = {
  api: "${api%/}",
  cognito: { dominio: "$(salida CognitoDominio "$PILA_WEB")", cliente: "$(salida Cliente "$PILA_WEB")" },
};
EOF
  aws s3 sync "$RAIZ/web" "s3://$bucket" --delete --exclude config.js
  aws s3 cp "$config" "s3://$bucket/config.js" --cache-control no-cache \
    --content-type application/javascript
  rm -f "$config"
  # "/*" no es una ruta de Windows: que Git Bash no la convierta
  MSYS2_ARG_CONV_EXCL="*" aws cloudfront create-invalidation \
    --distribution-id "$(salida Distribucion "$PILA_WEB")" --paths "/*" >/dev/null
  echo "Página: $(salida Pagina "$PILA_WEB")  (CloudFront tarda unos minutos en refrescar)"
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
    commit=$(commit_actual)
    echo "Commit de la imagen: $commit"
    aws ecr get-login-password | docker login --username AWS --password-stdin "${uri%%/*}"
    # Fargate corre x86_64; --platform evita una imagen ARM si se construye en un Mac M
    docker build --platform linux/amd64 --build-arg CDCOL_COMMIT="$commit" \
      -t "$uri:latest" -t "$uri:${commit:0:7}" "$RAIZ"
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
    echo "Registros: $0 registros"
    ;;

  registros)
    aws logs tail /cdcol-fm/batch --follow
    ;;

  medicion)
    zona="${2:?uso: medicion ZONA MES}"; mes="${3:?falta MES}"
    aws s3 cp "s3://$(salida Bucket)/zonas/$zona/mediciones/$mes.json" -
    ;;

  web-llave)
    set -a; . "$RAIZ/.env"; set +a
    valor=$(printf %s "${ANTHROPIC_API_KEY:-}" | tr -d '\r')
    [ -n "$valor" ] || { echo "falta ANTHROPIC_API_KEY en .env" >&2; exit 1; }
    aws ssm put-parameter --name /cdcol-fm/anthropic-api-key --type SecureString --overwrite \
      --value "$valor" >/dev/null
    echo "/cdcol-fm/anthropic-api-key listo"
    ;;

  web)
    aws ssm get-parameter --name /cdcol-fm/anthropic-api-key >/dev/null 2>&1 \
      || { echo "Primero: $0 web-llave" >&2; exit 1; }
    # 1. la pila sin tocar la función (la primera vez crea el repositorio de la imagen)
    previa=$(aws cloudformation describe-stacks --stack-name "$PILA_WEB" \
      --query "Stacks[0].Parameters[?ParameterKey=='ImagenWeb'].ParameterValue" \
      --output text 2>/dev/null || true)
    [ "$previa" = "None" ] && previa=""
    echo "1/3 Pila $PILA_WEB"
    desplegar_web "$previa"
    # 2. la imagen. --provenance=false: Lambda no acepta el índice OCI que agrega buildx
    uri=$(salida Imagen "$PILA_WEB")
    commit=$(commit_actual)
    echo "2/3 Imagen (commit $commit)"
    aws ecr get-login-password | docker login --username AWS --password-stdin "${uri%%/*}"
    docker build --platform linux/amd64 --provenance=false --build-arg CDCOL_COMMIT="$commit" \
      -f "$RAIZ/infra/aws/web.Dockerfile" -t "$uri:${commit:0:7}" "$RAIZ"
    docker push "$uri:${commit:0:7}"
    digest=$(aws ecr describe-images --repository-name cdcol-fm-web \
      --image-ids imageTag="${commit:0:7}" --query 'imageDetails[0].imageDigest' --output text)
    # 3. la función con esa imagen (por digest: cada versión es un cambio) y la página
    echo "3/3 Función y página"
    desplegar_web "$uri@$digest"
    publicar_web
    echo "Para dar acceso: $0 usuario CORREO"
    ;;

  web-publicar)
    publicar_web
    ;;

  usuario)
    correo="${2:?uso: usuario CORREO}"
    aws cognito-idp admin-create-user --user-pool-id "$(salida Usuarios "$PILA_WEB")" \
      --username "$correo" --desired-delivery-mediums EMAIL \
      --user-attributes Name=email,Value="$correo" Name=email_verified,Value=true >/dev/null
    echo "$correo creado: le llega un correo con una contraseña temporal (vence en 7 días)."
    ;;

  web-registros)
    aws logs tail /aws/lambda/cdcol-fm-web --follow
    ;;

  *)
    sed -n '2,18p' "$0"; exit 1 ;;
esac
