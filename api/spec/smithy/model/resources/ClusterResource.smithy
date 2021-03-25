namespace parallelcluster

resource Cluster {
    identifiers: { clusterName: ClusterName },
    create: CreateCluster,
    list: ListClusters,
    read: DescribeCluster,
    delete: DeleteCluster,
    update: UpdateCluster,
    operations: [
    ],
}

resource ClusterInstances {
    identifiers: { clusterName: ClusterName },
    read: DescribeClusterInstances,
    delete: DeleteClusterInstances,
}

resource ClusterComputeFleetStatus {
    identifiers: { clusterName: ClusterName },
    read: DescribeComputeFleetStatus,
    update: UpdateComputeFleetStatus,
}
