namespace parallelcluster

// Reuse the response as it is identical between cluster / image stack event requests
@suppress(["InputOutputStructureReuse"])
@paginated
@readonly
@http(method: "GET", uri: "/v3/images/custom/{imageId}/logstreams/{logStreamName}", code: 200)
@tags(["Image Logs"])
@documentation("Retrieve the events associated with an image build.")
operation GetImageLogEvents {
    input: GetImageLogEventsRequest,
    output: GetLogEventsResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure GetImageLogEventsRequest {
    @httpLabel
    @required
    imageId: ImageId,
    @httpQuery("region")
    region: Region,
    @httpLabel
    @required
    logStreamName: LogStreamName,
    @httpQuery("nextToken")
    nextToken: PaginationToken,
    @httpQuery("startFromHead")
    @documentation("If the value is true, the earliest log events are returned first. If the value is false, the latest log events are returned first. (Defaults to 'false'.)")
    startFromHead: Boolean,
    @httpQuery("limit")
    @documentation("The maximum number of log events returned. If you don't specify a value, the maximum is as many log events as can fit in a response size of 1 MB, up to 10,000 log events.")
    limit: Integer,
    @httpQuery("startTime")
    @documentation("The start of the time range, expressed in ISO 8601 format (e.g. '2021-01-01T20:00:00Z'). Events with a timestamp equal to this time or later than this time are included.")
    startTime: Timestamp,
    @httpQuery("endTime")
    @documentation("The end of the time range, expressed in ISO 8601 format (e.g. '2021-01-01T20:00:00Z'). Events with a timestamp equal to or later than this time are not included.")
    endTime: Timestamp,
}

