#!/bin/bash
set -e

PROJECT_ID="robles-ai-identity-project"
REGION="us-central1"
REPO_NAME="identity-api-repo"
SERVICE_NAME="identity-server"
CLOUD_RUN_SA="cloud-run-sa"
CLOUD_RUN_SA_EMAIL="$CLOUD_RUN_SA@$PROJECT_ID.iam.gserviceaccount.com"
CI_SA="github-deployer"
CI_SA_EMAIL="$CI_SA@$PROJECT_ID.iam.gserviceaccount.com"
DOMAIN="identity-api.robles.ai"

gcloud config set project $PROJECT_ID

echo "🧹 Iniciando limpieza en el proyecto: $PROJECT_ID"

# Eliminar dominio si existe
if gcloud beta run domain-mappings describe --domain "$DOMAIN" --region="$REGION" &> /dev/null; then
  echo "🗑️  Eliminando dominio '$DOMAIN'..."
  gcloud beta run domain-mappings delete --domain="$DOMAIN" --region="$REGION" --platform=managed --quiet
else
  echo "✅ Dominio '$DOMAIN' ya estaba eliminado."
fi

# Eliminar servicio Cloud Run si existe
if gcloud run services describe "$SERVICE_NAME" --platform=managed --region="$REGION" &> /dev/null; then
  echo "🗑️  Eliminando servicio de Cloud Run..."
  gcloud run services delete "$SERVICE_NAME" --platform=managed --region="$REGION" --quiet
else
  echo "✅ Servicio Cloud Run '$SERVICE_NAME' ya estaba eliminado."
fi

# Eliminar repositorio de Artifact Registry si existe
if gcloud artifacts repositories describe "$REPO_NAME" --location="$REGION" &> /dev/null; then
  echo "🗑️  Eliminando repositorio Artifact Registry..."
  gcloud artifacts repositories delete "$REPO_NAME" --location="$REGION" --quiet
else
  echo "✅ Repositorio '$REPO_NAME' ya estaba eliminado."
fi

# Eliminar cuentas de servicio (runtime + CI/CD) si existen
for SA_EMAIL in "$CLOUD_RUN_SA_EMAIL" "$CI_SA_EMAIL"; do
  if gcloud iam service-accounts describe "$SA_EMAIL" &> /dev/null; then
    echo "🗑️  Eliminando cuenta de servicio '$SA_EMAIL'..."
    gcloud iam service-accounts delete "$SA_EMAIL" --quiet
  else
    echo "✅ Cuenta de servicio '$SA_EMAIL' ya estaba eliminada."
  fi
done

echo -e "\n🎉 Limpieza completa sin errores."
