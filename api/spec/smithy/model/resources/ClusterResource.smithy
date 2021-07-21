namespace parallelcluster

resource Cluster {
    identifiers: { clusterName: ClusterName },
    put: CreateCluster,
    list: ListClusters,
    read: DescribeCluster,
    delete: DeleteCluster,
    update: UpdateCluster,
    operations: [],
}

resource ClusterInstances {
    identifiers: { clusterName: ClusterName },
    read: DescribeClusterInstances,
    delete: DeleteClusterInstances,
}

resource ClusterComputeFleet {
    identifiers: { clusterName: ClusterName },
    read: DescribeComputeFleet,
    update: UpdateComputeFleet,
}
