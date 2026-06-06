FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-cloud.txt .
RUN pip install --no-cache-dir -r requirements-cloud.txt

COPY cloud_app ./cloud_app
COPY templates ./templates

CMD exec gunicorn --bind :${PORT:-8080} --workers 1 --threads 8 --timeout 0 cloud_app.main:app

