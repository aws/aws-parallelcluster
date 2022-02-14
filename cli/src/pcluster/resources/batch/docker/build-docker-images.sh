#!/usr/bin/env bash
set -eu

retry() {
    local loop=1
    local max_retries=3
    local retry_delays=5

    set +e
    while true; do
        "$@" && break || {
            if [[ ${loop} -le ${max_retries} ]]; then
                echo "Command ($*) failed. Retrying..."
                loop=$((loop+1))
                sleep ${retry_delays}
            else
                echo "Command ($*) failed after ${max_retries} attempts."
                exit 1
            fi
        }
    done
    set -e
}

build_docker_image() {
    local image=$1
    echo "Building image ${image}"
    if [ ! -f "${image}/Dockerfile" ]; then
        echo "Dockerfile not found for image ${image}. Exiting..."
        exit 1
    fi
    retry docker build --build-arg AWS_REGION="${AWS_REGION}" -f "${image}/Dockerfile" -t "${IMAGE_REPO_NAME}:${image}" .
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
