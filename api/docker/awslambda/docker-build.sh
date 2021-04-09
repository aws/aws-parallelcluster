#!/usr/bin/env bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "${SCRIPT_DIR}/../../.."
docker build "$@" -f api/docker/awslambda/Dockerfile . -t pcluster-lambda

echo
echo "Use the following to run a shell in the container"
echo "  docker run -it --entrypoint /bin/bash pcluster-lambda"
echo
echo "Use the following to run a local AWS Lambda endpoint hosting the API"
echo "  docker run -p 9000:8080 pcluster-lambda"
echo "Then you can use the following to send requests to the local endpoint"
echo "  curl -XPOST \"http://localhost:9000/2015-03-31/functions/function/invocations\" -d \"{}\""
echo
echo "Use the following to run a local Flask development server hosting the API"
echo "  docker run --entrypoint python pcluster-lambda -m api.python_server.app"
echo "Then you can navigate to the following url to test the API: http://0.0.0.0:8080/ui"
echo "Note that to enable swagger-ui you have to build the docker with '--build-arg PROFILE=dev'"
echo
