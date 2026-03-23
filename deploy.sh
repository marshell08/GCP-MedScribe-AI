#!/bin/bash

# Cloud Run Deployment Script for MedScribe AI
# -----------------------------------------------------

# 1. Fetch Google Cloud Project configuration
PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
    echo "Error: No active gcloud project found. Run 'gcloud config set project [PROJECT]' first."
    exit 1
fi

SERVICE_NAME="medscribe-ai"
REGION="us-central1"
IMAGE_TAG="${REGION}-docker.pkg.dev/${PROJECT_ID}/medscribe-repo/${SERVICE_NAME}:latest"

echo "🚀 Starting deployment for Project: ${PROJECT_ID}"
echo "-----------------------------------------------------"

# 2. Build the Docker Container using Cloud Builds
echo "📦 Step 1: Submitting code to Google Cloud Builds..."
gcloud builds submit --tag "$IMAGE_TAG" .

if [ $? -ne 0 ]; then
    echo "❌ Build failed. Exiting."
    exit 1
fi

# 3. Deploy to Cloud Run
echo "📦 Step 2: Deploying container to Cloud Run..."

# Load local .env variables to pass into Cloud Run
if [ -f .env ]; then
    echo "Loading environment variables from local .env..."
    # Format environment variables for gcloud run deploy
    ENV_VARS=$(grep -v '^#' .env | grep '=' | tr '\n' ',' | sed 's/,$//')
else
    echo "⚠️  Warning: No .env file found. Deploying with empty environment variables."
    ENV_VARS=""
fi

gcloud run deploy "$SERVICE_NAME" \
    --image "$IMAGE_TAG" \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --update-env-vars "$ENV_VARS"

echo "-----------------------------------------------------"
echo "✅ Deployment finished successfully!"
