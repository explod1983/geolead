# Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# install deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy app
COPY backend/ .

# optional, but nice for docs
EXPOSE 8080

# run
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
