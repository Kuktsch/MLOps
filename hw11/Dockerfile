FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app:/app/hw8910
WORKDIR /app
COPY hw11/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY hw8910-broken/artifacts.py hw8910-broken/release.py hw8910-broken/model_backend.py ./hw8910/
COPY hw11/service.py hw11/client.py hw11/checks.py ./
COPY hw11/models/ ./models/
USER 10001:10001
EXPOSE 8091
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8091", "--timeout-graceful-shutdown", "32", "--no-access-log"]
