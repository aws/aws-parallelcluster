namespace parallelcluster

@paginated
@readonly
@http(method: "GET", uri: "/v3/clusters", code: 200)
@tags(["Cluster Operations"])
@documentation("Retrieve the list of existing clusters managed by the API. Deleted clusters are not listed by default.")
operation ListClusters {
    input: ListClustersRequest,
    output: ListClustersResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure ListClustersRequest {
    @httpQuery("region")
    @documentation("List clusters deployed to a given AWS Region. Defaults to the AWS region the API is deployed to.")
    region: Region,
    @httpQuery("nextToken")
    nextToken: PaginationToken,
    @httpQuery("clusterStatus")
    @documentation("Filter by cluster status.")
    clusterStatus: ClusterStatusFilteringOptions,
}

structure ListClustersResponse {
    nextToken: PaginationToken,

    @required
    items: ClusterSummaries,
}

list ClusterSummaries {
    member: ClusterInfoSummary
}

set ClusterStatusFilteringOptions {
    member: ClusterStatus
}
