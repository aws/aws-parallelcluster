namespace parallelcluster

@readonly
@http(method: "GET", uri: "/v3/clusters/{clusterName}/export_logs", code: 200)
@tags(["Cluster Logs"])
@documentation("Export the logs and stack events for a given cluster.")
operation ExportClusterLogs {
    input: ExportClusterLogsRequest,
    output: ExportClusterLogsResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure ExportClusterLogsRequest {
    @httpLabel
    @required
    clusterName: ClusterName,

    @httpQuery("region")
    @documentation("Region that the given cluster and bucket belong to.")
    region: Region,

    @httpQuery("bucket")
    @required
    @documentation("S3 bucket to export cluster logs data to. It must be in the same region of the cluster.")
    bucket: String,

    @httpQuery("bucketPrefix")
    @documentation("Keypath under which exported logs data will be stored in s3 bucket.")
    bucketPrefix: String,

    @httpQuery("startTime")
    @documentation("Start time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ss.sssZ (e.g. 1984-09-15T19:20:30.000Z), time elements might be omitted. Defaults to creation time.")
    @timestampFormat("date-time")
    startTime: Timestamp,

    @httpQuery("EndTime")
    @documentation("Start time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ss.sssZ (e.g. 1984-09-15T19:20:30.000Z), time elements might be omitted. Defaults to current time.")
    @timestampFormat("date-time")
    endTime: Timestamp,

    @httpQuery("filters")
    @documentation("Filter the log streams. Format: (Name=a,Values=1 Name=b,Values=2,3).\nAccepted filters are:\nprivate-dns-name - The short form of the private DNS name of the instance (e.g. ip-10-0-0-101).\nnode-type - The node type, the only accepted value for this filter is HeadNode.")
    filters: LogFilterList,
}

structure ExportClusterLogsResponse {
    @required
    @documentation("Message corresponding to the status of the result of this request.")
    message: String,

    @required
    @documentation("Task Id for the log export operation.")
    logExportTaskId: String,

    @required
    @documentation("URL that points to the location of the stored stack events.")
    stackEventsUrl: String,

    @required
    @documentation("URL that points to the location of the stored logs.")
    logEventsUrl: String,
}
