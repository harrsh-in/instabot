#!/bin/bash
# Production deployment script

set -e

echo "🚀 Deploying Instagram Webhook Server..."

# Load environment variables from .env file if it exists
if [ -f .env ]; then
    echo "📋 Loading environment from .env file..."
    set -a
    source .env
    set +a
else
    echo "⚠️  Warning: .env file not found. Using existing environment variables."
fi

# Check required environment variables
check_env() {
    if [ -z "$1" ]; then
        echo "❌ Error: $2 not set"
        exit 1
    fi
}

check_env "$FLASK_SECRET_KEY" "FLASK_SECRET_KEY"
check_env "$META_APP_ID" "META_APP_ID"
check_env "$META_APP_SECRET" "META_APP_SECRET"
check_env "$META_REDIRECT_URI" "META_REDIRECT_URI"
check_env "$META_VERIFY_TOKEN" "META_VERIFY_TOKEN"

# Create data directories
mkdir -p data/instance data/logs

# Build and deploy
echo "📦 Building Docker image..."
docker compose build --no-cache

echo "🛑 Stopping existing containers..."
docker compose down 2>/dev/null || true

echo "🚀 Starting new containers..."
docker compose up -d

echo "⏳ Waiting for health check..."
sleep 5

# Check if container is running
if docker compose ps | grep -q "Up"; then
    echo "✅ Deployment successful!"
    echo ""
    echo "📊 Container status:"
    docker compose ps
    echo ""
    echo "📜 Recent logs:"
    docker compose logs --tail=20
else
    echo "❌ Deployment failed!"
    docker compose logs
    exit 1
fi
