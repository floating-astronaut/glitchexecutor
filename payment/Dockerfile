FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN find /app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
EXPOSE 5002
CMD ["gunicorn", "--bind", "0.0.0.0:5002", "--workers", "1", "--timeout", "60", "--preload", "server:app"]
