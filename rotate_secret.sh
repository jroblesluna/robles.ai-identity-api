#!/bin/bash
set -e

# Rotate ONLY the FIREBASE_KEY secret and roll Cloud Run onto the new version —
# WITHOUT rebuilding the image. Use this when the credential changed but the code
# did not (takes seconds, not minutes). For code changes use update_docker.sh.

FIREBASE_KEY_PATH="./firebase_key.json"
if [ ! -f "$FIREBASE_KEY_PATH" ]; then
  echo "🛑 ERROR: $FIREBASE_KEY_PATH no encontrado. Colócalo antes de rotar."
  exit 1
fi

PROJECT_ID="identityverifierapp"
REGION="us-central1"
SERVICE_NAME="identity-server"
SECRET_NAME="FIREBASE_KEY"

echo "🔐 Añadiendo nueva versión del secreto $SECRET_NAME (valor oculto)..."
gcloud secrets versions add "$SECRET_NAME" --data-file="$FIREBASE_KEY_PATH" --project="$PROJECT_ID"

echo "🔄 Recargando el secreto en Cloud Run (sin rebuild)..."
gcloud run services update "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --update-secrets "/secrets/$SECRET_NAME=${SECRET_NAME}:latest"

echo "✅ Secreto rotado y recargado. La imagen no se reconstruyó."
