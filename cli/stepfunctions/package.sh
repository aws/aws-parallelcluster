#!/bin/bash
docker build -t cfncluster-stepfunctions $5
docker run -v $1:/var/package cfncluster-stepfunctions \
    pip install -r requirements-lambda.txt -t /var/package
aws cloudformation package \
    --template-file $1/template.yaml \
    --output-template-file $1/deploy.yaml \
    --s3-bucket $2
aws cloudformation deploy \
    --template-file $1/deploy.yaml \
    --capabilities CAPABILITY_IAM \
    --stack-name $3 \
    --region $4
