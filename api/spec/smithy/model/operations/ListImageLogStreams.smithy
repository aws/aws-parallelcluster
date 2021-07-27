namespace parallelcluster

@suppress(["InputOutputStructureReuse"])
@paginated
@readonly
@http(method: "GET", uri: "/v3/images/custom/{imageId}/logstreams", code: 200)
@tags(["Image Logs"])
@documentation("Retrieve the list of log streams associated with a cluster.")
operation ListImageLogStreams {
    input: ListImageLogStreamsRequest,
    output: ListLogStreamsResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure ListImageLogStreamsRequest {
    @httpQuery("region")
    @documentation("Region that the given cluster belongs to.")
    region: Region,

    @httpLabel
    @required
    imageId: ImageId,

    @httpQuery("nextToken")
    nextToken: PaginationToken,
}
