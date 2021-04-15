# AWS ParallelCluster API

## API Specification

The ParallelCluster API specification, defined in the `spec/` directory, is available in two different formats:
[OpenAPI](https://swagger.io/specification/) and [Smithy](https://awslabs.github.io/smithy/).

The OpenAPI definition can be found in the `spec/openapi/ParallelCluster.openapi.yaml` file while the Smithy model is
defined in the `spec/smithy` directory.

The OpenAPI model can be automatically generated from the Smithy one by using the following Gradle task:
```bash
./gradlew buildSmithyModel
```

Additional Gradle tasks are available in order to streamline the development of the API:
```bash
./gradlew tasks
...
OpenAPI Tools tasks
-------------------
openApiGenerate - Generate code via Open API Tools Generator for Open API 2.0 or 3.x specification documents.
openApiGenerators - Lists generators available via Open API Generators.
openApiMeta - Generates a new generator to be consumed via Open API Generator.
openApiValidate - Validates an Open API 2.0 or 3.x specification document.

ParallelCluster API tasks
-------------------------
buildSmithyModel - Build Smithy model and generate the OpenAPI spec file
generatePythonClient - Generate a Python client using Open API Tools Generator.
generatePythonServer - Generate a Python server using Open API Tools Generator.
redoc - Generate a standalone html page with the redoc documentation of the API
swaggerUI - Run a Docker container hosting a Swagger UI with the ParallelCluster API specs.
```

### OpenAPI Documentation Tools

From the OpenAPI model, a visual documentation can be produced, in either the [Swagger UI](https://swagger.io/tools/swagger-ui/)
or the [ReDoc](https://github.com/Redocly/redoc) format.

To run local server hosting the Swagger UI with live reloading enabled run the following command:
`./gradlew swaggerUI`.

You can then review the documentation by opening a browser to http://0.0.0.0:8080.
To stop the Docker container exposing the Swagger UI run `docker stop pcluster-swagger-ui`.

To generate a standalone HTML page with the API documentation in the ReDoc format run the following command:
`./gradlew redoc`. Once compiled the file will be available at `spec/openapi/ParallelCluster.openapi.redoc.html`.

### Generating the API Server Stub and API Client

The [OpenAPI Generator](https://openapi-generator.tech/) tool can be used to generate the client and the server
applications form the OpenAPI specification file.

In order to generate the server stub in Python language the [python-flask](https://openapi-generator.tech/docs/generators/python-flask)
generator can be invoked by running: `./gradlew generatePythonServer`. The code is generated under the 
`generated/python-server` directory.

In order to generate the client in Python language the [python](https://openapi-generator.tech/docs/generators/python)
generator can be invoked by running: `./gradlew generatePythonClient`. The code is generated under the
`generated/python-client` directory.

### Development Workflow

The usual development workflow to follow when extending the ParallelCluster API is the following:
1. Modify the Smithy model under `spec/smithy` in order to reflect the necessary API changes
2. Build and validate the Smithy model by running `./gradlew buildSmithyModel`. Review and solve errors and warnings
   produced by the Smithy build.
3. Review the OpenAPI model by eventually using one of the available documentation tools described above.
4. Open a PR to review the changes to the API.

Once the new model is reviewed and approved generate the server stub by running `./gradlew generatePythonServer`.
Import the newly generated models and controllers to the server code which is implemented in the `cli/src` directory.
Also apply the required changes to the `openapi.yaml` file.

#### GitHub Workflows

The ParallelCluster CI workflow (`workdlows/ci.yml`) contains a `validate-api-model` build step that verifies the
correctness of the API model evey time a PR is opened.

The ParallelCluster OpenAPI Generator workflow (`workdlows/openapi_generator.yml`) defines a `generate-openapi-model`
build step that automatically adds to the PR the generated OpenAPI model in case this was not included in the commit.

## Packaging the API as an AWS Lambda container

The `docker/awslambda` directory contains the definition of a Dockerfile that is used to package the ParallelCluster
API as an AWS Lambda function. Running the `docker/awslambda/docker-build.sh` script will produce a `pcluster-lambda`
Docker container that packages and exposes the ParallelCluster API in a format which is compatible with the AWS Lambda runtime.

### Running Testing and Debugging the API locally

Once the Docker image has been successfully built you have the following options:

#### Run a shell in the container
Use the following to run a shell in the container: `docker run -it --entrypoint /bin/bash pcluster-lambda`.

This is particularly useful to debug issues with the container runtime.

#### Run a local AWS Lambda endpoint
Use the following to run a local AWS Lambda endpoint hosting the API: `docker run -p 9000:8080 pcluster-lambda`

Then you can use the following to send requests to the local endpoint:
`curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d @docker/awslambda/test-events/event.json`

This is useful to test the integration with AWS Lambda.

#### Run the Flask development server
Use the following to run a local Flask development server hosting the API: `docker run --entrypoint python pcluster-lambda -m api.app`

Then you can navigate to the following url to test the API: `http://0.0.0.0:8080/ui`
Note that to enable swagger-ui you have to build the docker with `--build-arg PROFILE=dev`.

This is particularly useful to ignore the AWS Lambda layer and directly hit the Flask application with plain HTTP requests.
An even simpler way to do this which also offers live reloading of the API code, is to just ignore the Docker container
and run a local Flask server on your host by executing `cd ../cli/src && python -m api.app`

#### Run a local AWS APIGateway endpoint with SAM
The `docker/awslambda/sam` directory contains a sample [SAM](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html)
template that can be used to locally test the ParallelCluster API as if it were hosted behind an API Gateway endpoint.

To do so move to the `docker/awslambda/sam` directory and run `sam build && sam local start-api`. For further details and
to review all the testing features available through SAM please refer to the official
[SAM docs](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-test-and-debug.html).
