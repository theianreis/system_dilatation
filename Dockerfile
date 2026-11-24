FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv==0.13.1 && uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH"
ENV SYSTEM_DILATATION_DB=/data/database/sensores.db
VOLUME ["/data"]
ENTRYPOINT ["system-dilatation"]
CMD ["--help"]
