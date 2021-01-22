#!/usr/bin/env bash
set -eu

build_docker_image() {
    local image=$1
    local retries=5
    echo "Building image ${image}"
    if [ ! -f "${image}/Dockerfile" ]; then
        echo "Dockerfile not found for image ${image}. Exiting..."
        exit 1
    fi

    n=0
    until [ $n -gt ${retries} ]
    do
      # Try building the image max ${retries} times. If the command succeeds it breaks the loop
      echo "Docker build - trial #${n}"
      docker build -f "${image}/Dockerfile" -t "${IMAGE_REPO_NAME}:${image}" . && break
      echo "docker build failed."
      n=$((n+1))
      sleep ${RANDOM:0:1}
    done
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
