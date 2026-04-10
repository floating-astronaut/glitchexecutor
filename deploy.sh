#!/bin/bash
# GlitchExecutor Deployment Script
# Run this to deploy or update the full stack

set -e

echo "=========================================="
echo "GLITCHEXECUTOR DEPLOYMENT"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ ERROR: .env file not found!"
    echo ""
    echo "Please copy .env.template to .env and fill in your values:"
    echo "  cp .env.template .env"
    echo "  nano .env"
    echo ""
    exit 1
fi

echo "✅ .env file found"

# Source the .env file for local use
export $(grep -v '^#' .env | xargs)

# Check critical variables
if [ -z "$PG_PASSWORD" ] || [ "$PG_PASSWORD" = "CHANGE_ME_STRONG_PASSWORD" ]; then
    echo "⚠️  WARNING: Using default PostgreSQL password. Change this in production!"
fi

if [ -z "$ENCRYPTION_KEY" ] || [ "$ENCRYPTION_KEY" = "your_fernet_key_here" ]; then
    echo "❌ ERROR: ENCRYPTION_KEY not set in .env"
    echo "Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    exit 1
fi

echo "✅ Critical environment variables set"
echo ""

# Stop any existing containers
echo "Stopping existing containers..."
docker compose down 2>/dev/null || true

# Build and start
echo ""
echo "Building and starting containers..."
docker compose build --no-cache
docker compose up -d

echo ""
echo "Waiting for services to start..."
sleep 15

echo ""
echo "=========================================="
echo "HEALTH CHECKS"
echo "=========================================="

# Check Redis
echo ""
echo "Checking Redis..."
if docker compose exec -T redis redis-cli ping | grep -q "PONG"; then
    echo "✅ Redis is responding"
else
    echo "❌ Redis is not responding"
fi

# Check PostgreSQL
echo ""
echo "Checking PostgreSQL..."
if docker compose exec -T postgres pg_isready -U ${PG_USER:-glitch} -d glitchexecutor > /dev/null 2>&1; then
    echo "✅ PostgreSQL is ready"
else
    echo "❌ PostgreSQL is not ready"
fi

# Check tables
echo ""
echo "Checking database tables..."
docker compose exec -T postgres psql -U ${PG_USER:-glitch} -d glitchexecutor -c "\dt" | grep -E "customers|trades|query_log" && echo "✅ Tables exist" || echo "❌ Tables missing"

# Check Ensemble Engine
echo ""
echo "Checking Ensemble Engine..."
if curl -s http://localhost:8100/health | grep -q '"status": "ok"'; then
    echo "✅ Ensemble Engine health check passed"
else
    echo "⚠️  Ensemble Engine not ready yet (may need more time)"
fi

# Check if ensemble is writing to Redis
echo ""
echo "Checking Redis for ensemble data..."
sleep 5
if docker compose exec -T redis redis-cli KEYS "ensemble:*" | grep -q "ensemble:"; then
    echo "✅ Ensemble data found in Redis"
else
    echo "⚠️  No ensemble data yet (engine may still be starting)"
fi

# Container status
echo ""
echo "=========================================="
echo "CONTAINER STATUS"
echo "=========================================="
docker compose ps

echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE"
echo "=========================================="
echo ""
echo "Services:"
echo "  Redis:      localhost:6379"
echo "  PostgreSQL: localhost:5432"
echo "  Ensemble:   localhost:8100 (health check)"
echo ""
echo "View logs:"
echo "  docker compose logs -f ensemble"
echo "  docker compose logs -f telegram_bot"
echo "  docker compose logs -f executor"
echo ""
echo "To scale or restart:"
echo "  docker compose restart ensemble"
echo "  docker compose down && docker compose up -d"
echo ""
