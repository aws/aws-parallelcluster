namespace parallelcluster

@enum([
    {name: "PENDING", value: "pending"},
    {name: "ACTIVE", value: "active"},
    {name: "FAILED", value: "failed"},
])
string LoginNodesState

list LoginNodes {
    member: LoginNodesPool
}

structure LoginNodesPool {
    @required
    status: LoginNodesState,
    poolName: String
    address: String,
    scheme: String,
    healthyNodes: Integer,
    unhealthyNodes: Integer,
}
