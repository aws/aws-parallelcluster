namespace parallelcluster

@enum([
    {name: "PENDING", value: "pending"},
    {name: "ACTIVE", value: "active"},
    {name: "FAILED", value: "failed"},
])
string LoginNodesState

structure LoginNodesPool {
    @required
    status: LoginNodesState,
    address: String,
    scheme: String,
    healthyNodes: Integer,
    unhealthyNodes: Integer,
}
