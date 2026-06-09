FROM python:3.11-slim

WORKDIR /app

# 安裝 celery_kit 及其所有依賴（從本地 src/）
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e .

# example 額外需要的 runtime 依賴
RUN pip install --no-cache-dir psycopg2-binary requests

# 複製 Django 專案
COPY manage.py .
COPY example/ example/
