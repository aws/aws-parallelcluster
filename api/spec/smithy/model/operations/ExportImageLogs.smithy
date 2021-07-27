namespace parallelcluster

@readonly
@http(method: "GET", uri: "/v3/images/custom/{imageId}/export_logs", code: 200)
@tags(["Image Logs"])
@documentation("Export the logs and stack events for a given cluster.")
operation ExportImageLogs {
    input: ExportImageLogsRequest,
    output: ExportImageLogsResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure ExportImageLogsRequest {
    @httpLabel
    @required
    imageId: ImageId,

    @httpQuery("region")
    @documentation("Region that the given image and bucket belong to.")
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
    endTime: Timestamp
}

structure ExportImageLogsResponse {
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

    @required
    @documentation("URL that points to the location of the stored logs.")
    logEventsTaskId: String,
}
