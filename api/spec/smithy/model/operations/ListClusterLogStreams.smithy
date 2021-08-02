namespace parallelcluster

@suppress(["InputOutputStructureReuse"])
@paginated
@readonly
@http(method: "GET", uri: "/v3/clusters/{clusterName}/logstreams", code: 200)
@tags(["Cluster Logs"])
@documentation("Retrieve the list of log streams associated with a cluster.")
operation ListClusterLogStreams {
    input: ListClusterLogStreamsRequest,
    output: ListLogStreamsResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure ListClusterLogStreamsRequest {
    @httpQuery("region")
    @documentation("Region that the given cluster belongs to.")
    region: Region,

    @httpQuery("filters")
    @documentation("Filter the log streams. Format: 'Name=a,Values=1 Name=b,Values=2,3'.\nAccepted filters are:\nprivate-dns-name - The short form of the private DNS name of the instance (e.g. ip-10-0-0-101).\nnode-type - The node type, the only accepted value for this filter is HeadNode.")
    filters: LogFilterList,

    @httpLabel
    @required
    clusterName: ClusterName,

    @httpQuery("nextToken")
    nextToken: PaginationToken,
}

structure ListLogStreamsResponse {
    nextToken: PaginationToken,

    @required
    items: LogStreams,
}

