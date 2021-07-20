namespace parallelcluster

@http(method: "POST", uri: "/v3/clusters", code: 202)
@tags(["Cluster Operations"])
@documentation("Create a ParallelCluster managed in a given region.")
@idempotent
operation CreateCluster {
    input: CreateClusterRequest,
    output: CreateClusterResponse,
    errors: [
      InternalServiceException,
      CreateClusterBadRequestException,
      ConflictException,
      UnauthorizedClientError,
      LimitExceededException,
      DryrunOperationException,
    ]
}

structure CreateClusterRequest {
    @httpQuery("region")
    region: Region,
    @httpQuery("suppressValidators")
    @documentation("Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+)")
    suppressValidators: SuppressValidatorsList,
    @httpQuery("validationFailureLevel")
    @documentation("Min validation level that will cause the creation to fail. (Defaults to 'ERROR'.)")
    validationFailureLevel: ValidationLevel,
    @httpQuery("dryrun")
    @documentation("Only perform request validation without creating any resource. May be used to validate the cluster configuration.")
    dryrun: Boolean,
    @httpQuery("rollbackOnFailure")
    @documentation("When set it automatically initiates a cluster stack rollback on failures. (Defaults to true.)")
    rollbackOnFailure: Boolean,

    @httpQuery("clusterName")
    @required
    @documentation("Name of the cluster that will be created.")
    clusterName: ClusterName,
    @required
    clusterConfiguration: ClusterConfigurationData,
}

structure CreateClusterResponse {
    @required
    cluster: ClusterInfoSummary,
    @documentation("List of messages collected during cluster config validation whose level is lower than the 'validationFailureLevel' set by the user.")
    validationMessages: ValidationMessages
}
