#!/usr/bin/env bash
set -eu

push_docker_image() {
    local image=$1
    echo "Uploading image ${image}"
    S3_SUFFIX=""
    if [[ ${AWS_REGION} == cn-* ]]; then
        S3_SUFFIX=".cn"
    fi
    docker tag "${IMAGE_REPO_NAME}:${image}" "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com${S3_SUFFIX}/${IMAGE_REPO_NAME}:${image}"
    docker push "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com${S3_SUFFIX}/${IMAGE_REPO_NAME}:${image}"
}

if [ -z "${IMAGE}" ]; then
    for file in $(find `pwd` -type f -name Dockerfile); do
        IMAGE_TAG=$(dirname "${file}" | xargs basename)
        push_docker_image "${IMAGE_TAG}"
    done
else
    push_docker_image "${IMAGE}"
fi
