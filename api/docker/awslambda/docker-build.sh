#!/usr/bin/env bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT_DIR="${SCRIPT_DIR}/../../.."
docker build "$@" -f "${ROOT_DIR}/api/docker/awslambda/Dockerfile" "${ROOT_DIR}/cli" -t pcluster-lambda

echo
echo "Use the following to run a shell in the container"
echo "  docker run -it --entrypoint /bin/bash pcluster-lambda"
echo
echo "Use the following to run a local AWS Lambda endpoint hosting the API"
echo "  docker run -e POWERTOOLS_TRACE_DISABLED=1 -e AWS_REGION=eu-west-1 -p 9000:8080 pcluster-lambda"
echo "Then you can use the following to send requests to the local endpoint"
echo "  curl -XPOST \"http://localhost:9000/2015-03-31/functions/function/invocations\" -d @${SCRIPT_DIR}/test-events/event.json"
echo
echo "Use the following to run a local Flask development server hosting the API"
echo "  docker run -p 8080:8080 --entrypoint python pcluster-lambda -m pcluster.api.flask_app"
echo "Then you can navigate to the following url to test the API: http://0.0.0.0:8080/ui"
echo "Note that to enable swagger-ui you have to build the docker with '--build-arg PROFILE=dev'"
echo
echo "Use the following command to push the built image to a public ECR repository"
echo "  aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws/<alias>/<repository-name>"
echo "  docker tag pcluster-lambda:latest public.ecr.aws/<alias>/<repository-name>:latest"
echo "  docker push public.ecr.aws/<alias>/<repository-name>:latest"
