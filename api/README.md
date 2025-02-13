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
      To avoid huge diffs import only models related to your modifications.
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

## Testing

The API is a facade ontop of the controllers (as well as the CLI) so much of the underlying functionality can be tested
through unit tests and integration tests that exercise the operations.

In order to test the API specifically, there are integraiton tests which will deploy the API and test the functionality using
the generated client.

### Invoking the API

Install requirements for the example:
```
pip install -r client/requirements.txt
```

Invoke a deployed ParallelCluster API:
```
python client/example.py --region [REGION] --stack-name [PCAPI_STACK_NAME]
```

### Testing with Docker
You can test ParallelCluster API locally with Docker.
To this aim you need to build the Docker image:
```
bash tests/docker-build.sh
```

then run ParallelCluster API as Flask application:
```
docker run -p 8080:8080 -v ~/.aws:/root/.aws:ro --entrypoint python pcluster-lambda -m pcluster.api.flask_app
```

Notice that, the application will use the AWS credentials of your local default profile, defined in `~/.aws/config`.
