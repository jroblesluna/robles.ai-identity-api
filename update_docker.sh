#!/bin/bash
set -e

# Fallback manual: el camino normal de despliegue es CI/CD por push a main
# (.github/workflows/deploy.yml). Este script rebuild + redeploy a mano.
echo "🚀 Actualizando código y redeploy en Cloud Run..."

# ────────── VARIABLES DEL PROYECTO ──────────
PROJECT_ID="robles-ai-identity-project"
REGION="us-central1"
SERVICE_NAME="identity-server"
REPO_NAME="my-repo"
IMAGE_NAME="identity-server"
TAG="latest"
CLOUD_RUN_SA="cloud-run-sa"
CLOUD_RUN_SA_EMAIL="$CLOUD_RUN_SA@$PROJECT_ID.iam.gserviceaccount.com"

# Configurar proyecto
echo "📁 Proyecto: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

# ────────── CONSTRUIR IMAGEN DOCKER ──────────
echo "🔧 Construyendo imagen Docker (Kaniko cache) y subiendo a Artifact Registry..."
# Uses cloudbuild.yaml with Kaniko layer caching: a code-only change reuses the
# heavy cached layers (insightface install + baked buffalo_l model) and only
# rebuilds the final COPY layer.
gcloud builds submit --config cloudbuild.yaml --project="$PROJECT_ID" .

# ────────── DESPLIEGUE EN CLOUD RUN ──────────
# Sin Firebase: estado async en memoria (--max-instances=1), imágenes por base64.
echo "🚀 Desplegando nueva versión del servicio..."
gcloud run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$IMAGE_NAME:$TAG" \
  --region="$REGION" \
  --platform=managed \
  --memory=4Gi \
  --max-instances=1 \
  --allow-unauthenticated \
  --service-account="$CLOUD_RUN_SA_EMAIL" \
  --set-env-vars="^|^ALLOWED_ORIGINS=https://robles.ai,https://www.robles.ai"

echo "✅ Código actualizado y desplegado exitosamente."
