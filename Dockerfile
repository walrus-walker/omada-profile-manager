FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Create data directory for SQLite
RUN mkdir -p /data

EXPOSE 8095

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8095"]
