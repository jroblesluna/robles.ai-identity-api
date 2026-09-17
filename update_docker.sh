#!/bin/bash
set -e

echo "🚀 Actualizando código, secretos y redeploy en Cloud Run..."

# ────────── SECRETOS ──────────
# El secreto de este servicio es la clave de servicio de Firebase, que vive en
# firebase_key.json (gitignored) — nunca lo escribas aquí. En Cloud Run se monta
# como archivo en /secrets/FIREBASE_KEY.
FIREBASE_KEY_PATH="./firebase_key.json"
if [ ! -f "$FIREBASE_KEY_PATH" ]; then
  echo "🛑 ERROR: $FIREBASE_KEY_PATH no encontrado. Colócalo antes de desplegar."
  exit 1
fi

# ────────── VARIABLES DEL PROYECTO ──────────
PROJECT_ID="identityverifierapp"
REGION="us-central1"
SERVICE_NAME="identity-server"
REPO_NAME="my-repo"
IMAGE_NAME="identity-server"
TAG="latest"
SECRET_NAME="FIREBASE_KEY"
STORAGE_BUCKET_NAME="identityverifierapp.firebasestorage.app"
CLOUD_RUN_SA="cloud-run-sa"
CLOUD_RUN_SA_EMAIL="$CLOUD_RUN_SA@$PROJECT_ID.iam.gserviceaccount.com"

# Configurar proyecto
echo "📁 Proyecto: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

# ────────── ACTUALIZAR SECRETO EN SECRET MANAGER ──────────
echo "🔐 Creando o actualizando secreto $SECRET_NAME (valor oculto)..."
if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" > /dev/null 2>&1; then
  echo "🟡 Secreto $SECRET_NAME ya existe. Actualizando..."
  gcloud secrets versions add "$SECRET_NAME" --data-file="$FIREBASE_KEY_PATH" --project="$PROJECT_ID"
else
  echo "👤 Creando secreto $SECRET_NAME..."
  gcloud secrets create "$SECRET_NAME" --data-file="$FIREBASE_KEY_PATH" --replication-policy="automatic" --project="$PROJECT_ID"
fi

# ────────── CONSTRUIR IMAGEN DOCKER ──────────
echo "🔧 Construyendo imagen Docker y subiendo a Artifact Registry..."
# NOTE: identity's image (InsightFace + models) is large; pulling the previous
# image for --cache-from caching is slower than just rebuilding, so we build
# directly with --tag (unlike rag/langchain, whose caching pays off).
gcloud builds submit --tag "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$IMAGE_NAME:$TAG" --project="$PROJECT_ID" .

# ────────── DESPLIEGUE EN CLOUD RUN ──────────
echo "🚀 Desplegando nueva versión del servicio..."
gcloud run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$IMAGE_NAME:$TAG" \
  --region="$REGION" \
  --platform=managed \
  --memory=4Gi \
  --allow-unauthenticated \
  --service-account="$CLOUD_RUN_SA_EMAIL" \
  --set-env-vars="STORAGE_BUCKET_NAME=$STORAGE_BUCKET_NAME" \
  --set-secrets="/secrets/$SECRET_NAME=${SECRET_NAME}:latest"

echo "✅ Código, secretos y variables actualizados y desplegados exitosamente."
