# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install uv && uv sync --frozen --no-dev
ENV PYTHONPATH=/app/src
CMD ["uv", "run", "uvicorn", "scie.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
