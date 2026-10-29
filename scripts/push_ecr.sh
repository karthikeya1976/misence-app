#!/usr/bin/env bash
# Build the backend image and push it to ECR. Creates the repository on first run.
# Usage: scripts/push_ecr.sh [region] [repo-name] [tag]
# Needs AWS credentials with ecr:* on the target account and a running Docker daemon.
set -euo pipefail

REGION="${1:-us-east-2}"
REPO="${2:-misence-backend}"
TAG="${3:-$(git rev-parse --short HEAD)}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --region "$REGION" \
       --image-scanning-configuration scanOnPush=true >/dev/null

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

docker build -t "${REPO}:${TAG}" backend/
docker tag "${REPO}:${TAG}" "${REGISTRY}/${REPO}:${TAG}"
docker tag "${REPO}:${TAG}" "${REGISTRY}/${REPO}:latest"
docker push "${REGISTRY}/${REPO}:${TAG}"
docker push "${REGISTRY}/${REPO}:latest"

echo "Pushed ${REGISTRY}/${REPO}:${TAG}"
