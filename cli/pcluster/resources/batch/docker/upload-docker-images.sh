#!/usr/bin/env bash
set -eu

push_docker_image() {
    local image=$1
    echo "Uploading image image"
    docker tag "${IMAGE_REPO_NAME}:${image}" "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${IMAGE_REPO_NAME}:${image}"
    docker push "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${IMAGE_REPO_NAME}:${image}"
}

if [ -z "${IMAGE}" ]; then
    for file in $(find `pwd` -type f -name Dockerfile); do
        IMAGE_TAG=$(dirname "${file}" | xargs basename)
        push_docker_image "${IMAGE_TAG}"
    done
else
    push_docker_image "${IMAGE}"
fi
