#!/usr/bin/env bash
set -eu

build_docker_image() {
    local image=$1
    echo "Building image ${image}"
    if [ ! -f "${image}/Dockerfile" ]; then
        echo "Dockerfile not found for image ${image}. Exiting..."
        exit 1
    fi
    docker build -f "${image}/Dockerfile" -t "${IMAGE_REPO_NAME}:${image}" .
}

if [ -z "${IMAGE}" ]; then
    echo "No image to build specified. Building all images..."
    for file in $(find `pwd` -type f -name Dockerfile); do
        IMAGE_TAG=$(dirname "${file}" | xargs basename)
        build_docker_image "${IMAGE_TAG}"
    done
else
    build_docker_image "${IMAGE}"
fi
