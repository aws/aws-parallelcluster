namespace parallelcluster

@pattern("^[a-zA-Z][a-zA-Z0-9-]+$")
@documentation("Name of the cluster")
string ClusterName

set SuppressValidatorsList {
   member: SuppressValidatorExpression
}

@pattern("^(ALL|type:[A-Za-z0-9]+)$")
string SuppressValidatorExpression

structure ClusterInfoSummary {
    @required
    @documentation("Name of the cluster.")
    clusterName: ClusterName,
    @required
    @documentation("AWS region where the cluster is created.")
    region: Region,
    @required
    @documentation("ParallelCluster version used to create the cluster.")
    version: Version,
    @required
    @documentation("ARN of the main CloudFormation stack.")
    cloudformationStackArn: String,
    @required
    @documentation("Status of the CloudFormation stack provisioning the cluster infrastructure.")
    cloudformationStackStatus: CloudFormationStackStatus,
    @required
    @documentation("Status of the cluster infrastructure.")
    clusterStatus: ClusterStatus,
    @documentation("Scheduler of the cluster.")
    scheduler: Scheduler,
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
    {name: "START_REQUESTED", value: "START_REQUESTED"},  // works only with Slurm
    {name: "STARTING", value: "STARTING"},  // works only with Slurm
    {name: "RUNNING", value: "RUNNING"},  // works only with Slurm
    {name: "PROTECTED", value: "PROTECTED"},  // works only with Slurm
    {name: "STOP_REQUESTED", value: "STOP_REQUESTED"},  // works only with Slurm
    {name: "STOPPING", value: "STOPPING"},  // works only with Slurm
    {name: "STOPPED", value: "STOPPED"},  // works only with Slurm
    {name: "UNKNOWN", value: "UNKNOWN"},  // works only with Slurm
    {name: "ENABLED", value: "ENABLED"},  // works only with AWS Batch
    {name: "DISABLED", value: "DISABLED"},  // works only with AWS Batch
])
string ComputeFleetStatus

structure ClusterConfigurationStructure {
    @documentation("URL of the cluster configuration file.")
    url: String,
}

@documentation("Cluster configuration as a YAML document.")
string ClusterConfigurationData

list ChangeSet {
    member: Change
}

structure Change {
    parameter: String,
    currentValue: String,
    requestedValue: String,
}

structure Scheduler {
    @required
    type: String,
    metadata: Metadata,
}

structure Metadata {
    name: String,
    version: String,
}

list Failures {
    member: Failure
}

structure Failure {
    @documentation("Failure code when the cluster stack is in CREATE_FAILED status.")
    failureCode: String,
    @documentation("Failure reason when the cluster stack is in CREATE_FAILED status.")
    failureReason: String,
}