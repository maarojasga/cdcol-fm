# Imagen para correr cdcol-fm en cualquier computador con Docker, sin instalar Python.
#   docker compose run --rm cdcol ard prueba --s1 cdse
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH

WORKDIR /app
# primero solo las dependencias, para que cambiar el código no reinstale todo
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --extra cubo --extra radar --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --locked --no-dev --extra cubo --extra radar

# los productos se escriben en /datos, que se monta desde el computador
WORKDIR /datos
ENTRYPOINT ["cdcol"]
CMD ["--help"]
