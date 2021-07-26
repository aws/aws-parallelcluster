namespace parallelcluster

@http(method: "PATCH", uri: "/v3/clusters/{clusterName}/computefleet", code: 204)
@tags(["Cluster ComputeFleet"])
@documentation("Update the status of the cluster compute fleet.")
operation UpdateComputeFleet {
    input: UpdateComputeFleetRequest,
    output: UpdateComputeFleetResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure UpdateComputeFleetRequest {
    @httpLabel
    @required
    clusterName: ClusterName,

    @httpQuery("region")
    region: Region,

    @required
    status: RequestedComputeFleetStatus,
}

structure UpdateComputeFleetResponse {
    @required
    @documentation("Status of the compute fleet.")
    status: ComputeFleetStatus,

    @documentation("Timestamp representing the last status update time.")
    @timestampFormat("date-time")
    lastStatusUpdatedTime: Timestamp,
}

@enum([
    {name: "START_REQUESTED", value: "START_REQUESTED"},
    {name: "STOP_REQUESTED", value: "STOP_REQUESTED"},
    {name: "ENABLED", value: "ENABLED"},  // works only with AWS Batch
    {name: "DISABLED", value: "DISABLED"},  // works only with AWS Batch
])
string RequestedComputeFleetStatus
