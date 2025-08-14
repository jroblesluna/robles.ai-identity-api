#!/bin/bash
set -e

PROJECT_ID="identityverifierapp"
REGION="us-central1"
REPO_NAME="my-repo"
SERVICE_NAME="identity-server"
IMAGE_NAME="identity-server"
TAG="latest"

echo "🚀 Actualizando solo el código y redeploy en Cloud Run..."

gcloud config set project "$PROJECT_ID"

echo "🔧 Construyendo imagen Docker y subiendo a Artifact Registry..."
gcloud builds submit --tag "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$IMAGE_NAME:$TAG"

echo "🚀 Desplegando nueva versión del servicio..."
gcloud run deploy "$SERVICE_NAME" \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$IMAGE_NAME:$TAG" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated

echo "✅ Código actualizado y desplegado exitosamente."