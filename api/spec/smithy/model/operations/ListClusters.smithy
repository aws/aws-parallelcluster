namespace parallelcluster

@paginated
@readonly
@http(method: "GET", uri: "/v3/clusters", code: 200)
@tags(["Cluster Operations"])
@documentation("Retrieve the list of existing clusters.")
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
    @documentation("List clusters deployed to a given AWS Region.")
    region: Region,
    @httpQuery("nextToken")
    nextToken: PaginationToken,
    @httpQuery("clusterStatus")
    @documentation("Filter by cluster status. (Defaults to all clusters.)")
    clusterStatus: ClusterStatusFilteringOptions,
}

structure ListClustersResponse {
    nextToken: PaginationToken,

    @required
    clusters: ClusterSummaries,
}

list ClusterSummaries {
    member: ClusterInfoSummary
}

@enum([
    {name: "CREATE_IN_PROGRESS", value: "CREATE_IN_PROGRESS"},
    {name: "CREATE_FAILED", value: "CREATE_FAILED"},
    {name: "CREATE_COMPLETE", value: "CREATE_COMPLETE"},
    {name: "DELETE_IN_PROGRESS", value: "DELETE_IN_PROGRESS"},
    {name: "DELETE_FAILED", value: "DELETE_FAILED"},
    {name: "UPDATE_IN_PROGRESS", value: "UPDATE_IN_PROGRESS"},
    {name: "UPDATE_COMPLETE", value: "UPDATE_COMPLETE"},
    {name: "UPDATE_FAILED", value: "UPDATE_FAILED"},
])
string ClusterStatusFilteringOption

set ClusterStatusFilteringOptions {
    member: ClusterStatusFilteringOption
}
