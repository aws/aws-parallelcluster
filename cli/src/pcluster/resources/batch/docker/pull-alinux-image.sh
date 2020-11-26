#!/usr/bin/env bash
set -euxo pipefail

pull_docker_image_from_ecr() {
    echo "Pulling amazonlinux:2 image from ECR"
    aws ecr get-login-password --region "${ALINUX_ECR_REGISTRY_REGION}" | docker login --username AWS --password-stdin "${ALINUX_ECR_REGISTRY}" || return 1
    docker pull "${ALINUX_ECR_REGISTRY}/amazonlinux:2" || return 1
    docker tag "${ALINUX_ECR_REGISTRY}/amazonlinux:2" amazonlinux:2
}

if [ "${IMAGE}" = "alinux" ] || [ "${IMAGE}" = "alinux2" ]; then
  if [ "${ARCHITECTURE}" = "x86_64" ]; then
    if pull_docker_image_from_ecr; then
      echo "Successfully pulled Amazon Linux image from ECR"
    else
      echo "Failed when pulling amazonlinux:2 image from ECR. Falling back to Docker Hub"
      docker pull amazonlinux:2
    fi
  else
    docker pull amazonlinux:2
  fi
fi
