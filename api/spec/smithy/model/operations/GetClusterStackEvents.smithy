namespace parallelcluster

// Reuse the response as it is identical between cluster / image stack event requests
@suppress(["InputOutputStructureReuse"])
@paginated
@readonly
@http(method: "GET", uri: "/v3/clusters/{clusterName}/stackevents", code: 200)
@tags(["Cluster Logs"])
@documentation("Retrieve the events associated with the stack for a given cluster.")
operation GetClusterStackEvents {
    input: GetClusterStackEventsRequest,
    output: GetStackEventsResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure GetClusterStackEventsRequest {
    @httpLabel
    @required
    clusterName: ClusterName,
    @httpQuery("region")
    region: Region,
    @httpQuery("nextToken")
    nextToken: PaginationToken
}
