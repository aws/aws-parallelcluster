namespace parallelcluster

use aws.protocols#restJson1
use aws.apigateway#integration
use aws.auth#sigv4
use aws.api#service

@paginated(inputToken: "nextToken", outputToken: "nextToken")
@restJson1
@integration(
    type: "aws_proxy",
    httpMethod: "POST",
    uri: "arn:${AWS::Partition}:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${ParallelClusterFunction.Arn}/invocations",
    credentials: "${APIGatewayExecutionRole.Arn}",
    payloadFormatVersion: "2.0"
)
@service(
    sdkId: "ParallelCluster"
)
@sigv4(name: "ParallelCluster")
@documentation("ParallelCluster API")
service ParallelCluster {
    version: "3.13.0",
    resources: [Cluster, ClusterInstances, ClusterComputeFleet, ClusterLogStream, ClusterStackEvents,
    ImageLogStream, ImageStackEvents, CustomImage, OfficialImage],
    operations: []
}
