#!/usr/bin/env bash
set -ex

docker run -p 8080:8080 -e URL=docs/ParallelCluster.openapi.yaml --name pcluster-swagger-ui -v "$(pwd)/openapi":/usr/share/nginx/html/docs/ swaggerapi/swagger-ui
