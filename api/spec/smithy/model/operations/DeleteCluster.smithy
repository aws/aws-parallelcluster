namespace parallelcluster

@http(method: "DELETE", uri: "/v3/clusters/{clusterName}", code: 202)
@tags(["Cluster Operations"])
@idempotent
@documentation("Initiate the deletion of a cluster.")
operation DeleteCluster {
    input: DeleteClusterRequest,
    output: DeleteClusterResponse,
    errors: [
      InternalServiceException,
      BadRequestException,
      NotFoundException,
      UnauthorizedClientError,
      LimitExceededException,
    ]
}

structure DeleteClusterRequest {
    @httpLabel
    @required
    clusterName: ClusterName,

    @httpQuery("region")
    region: Region,
}

structure DeleteClusterResponse {
    @required
    cluster: ClusterInfoSummary
}
