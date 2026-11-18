# Imagen de Lambda para la página del chat (ADR 0006): `cdcol web` con el adaptador web de Lambda,
# que convierte cada invocación en una petición HTTP al servidor. Solo el extra `chat`: sin el
# cálculo del ARD, para que arranque rápido. Se construye con `infra/aws/cdcol-aws.sh web`.
FROM python:3.12-slim

# rasterio trae GDAL en su wheel, pero necesita libexpat del sistema (la imagen slim no la trae)
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --extra chat --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --locked --no-dev --extra chat

ARG CDCOL_COMMIT=desconocido
# Lambda solo deja escribir en /tmp; el adaptador reenvía al puerto 8080
ENV CDCOL_COMMIT=$CDCOL_COMMIT HOME=/tmp AWS_LWA_PORT=8080
CMD ["cdcol", "web", "--puerto", "8080", "--no-abrir"]
