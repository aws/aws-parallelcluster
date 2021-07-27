namespace parallelcluster

resource Cluster {
    identifiers: { clusterName: ClusterName },
    put: CreateCluster,
    list: ListClusters,
    read: DescribeCluster,
    delete: DeleteCluster,
    update: UpdateCluster,
    operations: [ExportClusterLogs],
}

resource ClusterInstances {
    identifiers: { clusterName: ClusterName },
    read: DescribeClusterInstances,
    delete: DeleteClusterInstances,
}

resource ClusterLogStream {
    identifiers: { clusterName: ClusterName, logStreamName: LogStreamName },
    list: ListClusterLogStreams,
    read: GetClusterLogEvents
}

resource ClusterStackEvents {
    identifiers: { clusterName: ClusterName },
    read: GetClusterStackEvents
}

resource ClusterComputeFleet {
    identifiers: { clusterName: ClusterName },
    read: DescribeComputeFleet,
    update: UpdateComputeFleet,
}
