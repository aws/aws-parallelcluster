namespace parallelcluster

@http(method: "PATCH", uri: "/v3/clusters/{clusterName}/computefleet/status", code: 204)
@tags(["Cluster ComputeFleet"])
@documentation("Update the status of the cluster compute fleet.")
operation UpdateComputeFleetStatus {
    input: UpdateComputeFleetStatusRequest,
    output: UpdateComputeFleetStatusResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure UpdateComputeFleetStatusRequest {
    @httpLabel
    @required
    clusterName: ClusterName,

    @httpQuery("region")
    region: Region,

    @required
    status: RequestedComputeFleetStatus,
}

structure UpdateComputeFleetStatusResponse {
}

@enum([
    {name: "START_REQUESTED", value: "START_REQUESTED"},
    {name: "STOP_REQUESTED", value: "STOP_REQUESTED"},
    {name: "ENABLED", value: "ENABLED"},  // works only with AWS Batch
    {name: "DISABLED", value: "DISABLED"},  // works only with AWS Batch
])
string RequestedComputeFleetStatus
