### Stage 1: needed to retrieve the node binary for CDK
FROM public.ecr.aws/lambda/nodejs:14 AS nodejs_docker

### Stage 2: creates the wheel package from the pcluster source
FROM public.ecr.aws/lambda/python:3.8 AS build_pcluster

RUN python -m pip install --upgrade setuptools wheel pip
ADD src ./cli/src
COPY setup.py MANIFEST.in README ./cli/
RUN cd cli && python setup.py bdist_wheel

### Stage 3: prepares the AWS Lambda environment
FROM public.ecr.aws/lambda/python:3.8 AS pcluster_lambda

# Copy the node runtime
COPY --from=nodejs_docker /var/lang/bin/node /var/lang/bin
# Copy the aws-parallelcluster wheel package
COPY --from=build_pcluster /var/task/cli/dist/* ./dist/
# Install aws-parallelcluster
RUN python -m pip install --upgrade pip
RUN export PKG=(./dist/*.whl); python -m pip install "${PKG}[api]" && rm -rf ./dist

# When the PROFILE is set to dev the Flask application is started in debug mode and with SwaggerUI support
ARG PROFILE=prod
ENV PROFILE=${PROFILE}
# Install additional dependencies to start the SwaggerUI in dev mode
RUN if [ "${PROFILE}" = "dev" ]; then python -m pip install connexion[swagger-ui]; fi

CMD ["api.awslambda.entrypoint.lambda_handler"]
