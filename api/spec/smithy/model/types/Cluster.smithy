namespace parallelcluster

@pattern("^[a-zA-Z][a-zA-Z0-9-]+$")
@length(min: 5, max: 60)
@documentation("Name of the cluster")
string ClusterName

structure ClusterInfoSummary {
    @required
    @documentation("Name of the cluster")
    clusterName: ClusterName,
    @required
    @documentation("AWS region where the cluster is created")
    region: Region,
    @required
    @documentation("ParallelCluster version used to create the cluster")
    version: Version,
    @required
    @documentation("ARN of the main CloudFormation stack")
    cloudformationStackArn: String,
    @required
    @documentation("Status of the CloudFormation stack provisioning the cluster infrastructure.")
    cloudformationStackStatus: CloudFormationStatus,
    @required
    @documentation("Status of the cluster infrastructure")
    clusterStatus: ClusterStatus,
}

@enum([
    {name: "CREATE_IN_PROGRESS", value: "CREATE_IN_PROGRESS"},
    {name: "CREATE_FAILED", value: "CREATE_FAILED"},
    {name: "CREATE_COMPLETE", value: "CREATE_COMPLETE"},
    {name: "DELETE_IN_PROGRESS", value: "DELETE_IN_PROGRESS"},
    {name: "DELETE_FAILED", value: "DELETE_FAILED"},
    {name: "DELETE_COMPLETE", value: "DELETE_COMPLETE"},
    {name: "UPDATE_IN_PROGRESS", value: "UPDATE_IN_PROGRESS"},
    {name: "UPDATE_COMPLETE", value: "UPDATE_COMPLETE"},
    {name: "UPDATE_FAILED", value: "UPDATE_FAILED"},
])
string ClusterStatus

@enum([
    {name: "START_REQUESTED", value: "START_REQUESTED"},
    {name: "STARTING", value: "STARTING"},
    {name: "RUNNING", value: "RUNNING"},
    {name: "STOP_REQUESTED", value: "STOP_REQUESTED"},
    {name: "STOPPING", value: "STOPPING"},
    {name: "STOPPED", value: "STOPPED"},
    {name: "ENABLED", value: "ENABLED"},  // works only with AWS Batch
    {name: "DISABLED", value: "DISABLED"},  // works only with AWS Batch
])
string ComputeFleetStatus

structure ClusterConfigurationStructure {
    @documentation("S3 Url pointing to the cluster configuration file.")
    s3Url: String,
}

@documentation("Cluster configuration as a YAML document")
blob ClusterConfigurationData
