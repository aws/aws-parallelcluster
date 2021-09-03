namespace parallelcluster

@enum([
    {name: "PENDING", value: "pending"},
    {name: "RUNNING", value: "running"},
    {name: "SHUTTING_DOWN", value: "shutting-down"},
    {name: "TERMINATED", value: "terminated"},
    {name: "STOPPING", value: "stopping"},
    {name: "STOPPED", value: "stopped"},
])
string InstanceState

@enum([
    {name: "HEADNODE", value: "HeadNode"},
    {name: "COMPUTENODE", value: "ComputeNode"},
])
string NodeType

structure EC2Instance {
    @required
    instanceId: String,
    @required
    instanceType: String,
    @required
    @timestampFormat("date-time")
    launchTime: Timestamp,
    @required
    privateIpAddress: String, // only primary?
    publicIpAddress: String,
    @required
    state: InstanceState
}
