FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy ensemble code
COPY . .

# Expose health check port
EXPOSE 8100

CMD ["python", "engine.py"]
