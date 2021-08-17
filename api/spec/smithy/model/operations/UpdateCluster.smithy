namespace parallelcluster

@http(method: "PUT", uri: "/v3/clusters/{clusterName}", code: 202)
@tags(["Cluster Operations"])
@idempotent
@documentation("Update a cluster managed in a given region.")
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
    @documentation("Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+)")
    suppressValidators: SuppressValidatorsList,
    @httpQuery("validationFailureLevel")
    @documentation("Min validation level that will cause the update to fail. (Defaults to 'ERROR'.)")
    validationFailureLevel: ValidationLevel,
    @httpQuery("region")
    region: Region,
    @httpQuery("dryrun")
    @documentation("Only perform request validation without creating any resource. May be used to validate the cluster configuration and update requirements. (Defaults to 'false'.)")
    dryrun: Boolean,
    @httpQuery("forceUpdate")
    @documentation("Force update by ignoring the update validation errors. (Defaults to 'false'.)")
    forceUpdate: Boolean,

    @required
    clusterConfiguration: ClusterConfigurationData,
}

structure UpdateClusterResponse {
    @required
    cluster: ClusterInfoSummary,
    @documentation("List of messages collected during cluster config validation whose level is lower than the 'validationFailureLevel' set by the user.")
    validationMessages: ValidationMessages,
    @required
    @documentation("List of configuration changes requested by the update operation.")
    changeSet: ChangeSet
}
