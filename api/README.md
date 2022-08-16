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
`client/src` directory.

### Development Workflow

The usual development workflow to follow when extending the ParallelCluster API is the following:
1. Modify the Smithy model under `spec/smithy` in order to reflect the necessary API changes
2. Build and validate the Smithy model by running `./gradlew buildSmithyModel`. Review and solve errors and warnings
   produced by the Smithy build.
3. Review the OpenAPI model that is generated under `spec/openapi/ParallelCluster.openapi.yaml` by eventually using
   one of the available documentation tools described above. Commit the changes.
4. Run `./gradlew generatePythonServer` to generate the server stub under the `generated/python-server` directory.
   The generated stub will reflect the same code structure as in `cli/src/pcluster/api`. Import the newly applied changes
   to the aws-parallelcluster source code:
   1. Changes to the API request/response model require changes to files under `cli/src/pcluster/api/models`. The
      newly generated models in the server stub can be imported as is, just mind fixing unused imports and formatting.
   2. Changes to the API operations and request/response model require an update to the controllers (namely the handlers
      of the various API endpoints). The updated controller signature can be retrieved from the generated stub files and
      relevant changes need to be applied to controllers under the `cli/src/pcluster/api/controllers` directory.
   3. Any API change will generate a change in the OpenAPI spec. Please import the newly changes available in the generated
      stub to `cli/src/pcluster/api/openapi/openapi.yaml`. For each diff with the respect to the generated file please add
      an `#  override: reason` comment documenting why this is required.
5. Generate the new client by running `./gradlew generatePythonClient` and commit the changes in a separate commit.
6. Open a PR to review the changes to the API.

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
Use the following to run a local AWS Lambda endpoint hosting the API: `docker run -e POWERTOOLS_TRACE_DISABLED=1 -e AWS_REGION=eu-west-1 -p 9000:8080 pcluster-lambda`

Then you can use the following to send requests to the local endpoint:
`curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d @docker/awslambda/test-events/event.json`

This is useful to test the integration with AWS Lambda.

#### Run the Flask development server
Use the following to run a local Flask development server hosting the API: `docker run -p 8080:8080 --entrypoint python pcluster-lambda -m pcluster.api.flask_app`

Then you can navigate to the following url to test the API: `http://0.0.0.0:8080/ui`
Note that to enable swagger-ui you have to build the docker with `--build-arg PROFILE=dev`.

This is particularly useful to ignore the AWS Lambda layer and directly hit the Flask application with plain HTTP requests.
An even simpler way to do this which also offers live reloading of the API code, is to just ignore the Docker container
and run a local Flask server on your host by executing `cd ../cli/src && python -m pcluster.api.flask_app`

## Deploy the API test infrastructure with SAM cli (API Gateway + Lambda)
The Serverless Application Model Command Line Interface (SAM CLI) is an extension of the AWS CLI that adds functionality
for building and testing Lambda applications. It uses Docker to run your functions in an Amazon Linux environment that
matches Lambda. It can also emulate your application's build environment and API.

To use the SAM CLI, you need the following tools.

* SAM CLI - [Install the SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
* Docker - [Install Docker community edition](https://hub.docker.com/search/?type=edition&offering=community)

You may need the following for local testing.
* [Python 3 installed](https://www.python.org/downloads/)

The `docker/awslambda/sam` directory contains a sample [SAM](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html)
template that can be used to test the ParallelCluster API.

### Run a local AWS APIGateway endpoint with SAM
The SAM template can be used together with the SAM CLI to locally test the ParallelCluster API as if it were hosted
behind an API Gateway endpoint.

To do so move to the `docker/awslambda/sam` directory and run:

```bash
sam build
sam local start-api
```

To only invoke the AWS Lambda function locally you can run:
```bash
sam build
sam local invoke ParallelClusterFunction --event ../test-events/event.json
```

For further details and
to review all the testing features available through SAM please refer to the official
[SAM docs](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-test-and-debug.html).

### Deploy the API test infrastructure
To build and deploy your application for the first time, run the following in your shell:

```bash
sam build
sam deploy --guided
```

The first command will build a docker image from a Dockerfile and then copy the source of your application inside the Docker image.
The second command will package and deploy your application to AWS, with a series of prompts.

#### Fetch, tail, and filter Lambda function logs

To simplify troubleshooting, SAM CLI has a command called `sam logs`. `sam logs` lets you fetch logs generated by your
deployed Lambda function from the command line. In addition to printing the logs on the terminal, this command has
several nifty features to help you quickly find the bug.

NOTE: This command works for all AWS Lambda functions; not just the ones you deploy using SAM.

```bash
sam logs -n ParallelClusterFunction --stack-name pcluster-lambda --tail
```

You can find more information and examples about filtering Lambda function logs in the 
[SAM CLI Documentation](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-logging.html).
