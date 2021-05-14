namespace parallelcluster

@http(method: "PUT", uri: "/v3/clusters/{clusterName}", code: 202)
@tags(["Cluster Operations"])
@idempotent
operation UpdateCluster {
    input: UpdateClusterRequest,
    output: UpdateClusterResponse,
    errors: [
        InternalServiceException,
        UpdateClusterBadRequestException,
        ConflictException,
        UnauthorizedClientError,
        NotFoundException,
        LimitExceededException,
        DryrunOperationException,
    ]
}

structure UpdateClusterRequest {
    @httpLabel
    @required
    clusterName: ClusterName,

    @httpQuery("suppressValidators")
    @documentation("Identifies one or more config validators to suppress. Format: ALL|id:$value|level:(info|error|warning)|type:$value")
    suppressValidators: SuppressValidatorsList,
    @httpQuery("validationFailureLevel")
    @documentation("Min validation level that will cause the update to fail. Defaults to 'error'.")
    validationFailureLevel: ValidationLevel,
    @httpQuery("region")
    region: Region,
    @httpQuery("dryrun")
    @documentation("Only perform request validation without creating any resource. It can be used to validate the cluster configuration and update requirements. Response code: 200")
    dryrun: Boolean,
    @httpQuery("forceUpdate")
    @documentation("Force update by ignoring the update validation errors.")
    forceUpdate: Boolean,
    @idempotencyToken
    @httpQuery("clientToken")
    @documentation("Idempotency token that can be set by the client so that retries for the same request are idempotent")
    clientToken: String,

    @required
    clusterConfiguration: ClusterConfigurationData,
}

structure UpdateClusterResponse {
    @required
    cluster: ClusterInfoSummary,
    @required
    @documentation("List of messages collected during cluster config validation whose level is lower than the validationFailureLevel set by the user")
    validationMessages: ValidationMessages,
    @required
    @documentation("List of configuration changes requested by the update operation")
    changeSet: ChangeSet
}

list ChangeSet {
    member: Change
}

structure Change {
    parameter: String,
    currentValue: String,
    requestedValue: String,
}
