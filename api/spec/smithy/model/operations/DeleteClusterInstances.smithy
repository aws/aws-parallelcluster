namespace parallelcluster

@http(method: "DELETE", uri: "/v3/clusters/{clusterName}/instances", code: 202)
@tags(["Cluster Instances"])
@idempotent
@documentation("Initiate the forced termination of all cluster compute nodes. Does not work with AWS Batch clusters")
operation DeleteClusterInstances {
    input: DeleteClusterInstancesRequest,
    output: DeleteClusterInstancesResponse,
    errors: [
      InternalServiceException,
      BadRequestException,
      NotFoundException,
      UnauthorizedClientError,
      LimitExceededException,
    ]
}

structure DeleteClusterInstancesRequest {
    @httpLabel
    @required
    clusterName: ClusterName,
    @httpQuery("region")
    region: Region,
    @httpQuery("force")
    @documentation("Force the deletion also when the cluster id is not found.")
    force: Boolean,
}

structure DeleteClusterInstancesResponse {
}
