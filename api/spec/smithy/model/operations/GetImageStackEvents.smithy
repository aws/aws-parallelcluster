namespace parallelcluster

@suppress(["MissingPaginatedTrait", "PaginatedTrait", "InputOutputStructureReuse"])
@paginated
@readonly
@http(method: "GET", uri: "/v3/images/custom/{imageId}/stackevents", code: 200)
@tags(["Image Logs"])
@documentation("Retrieve the events associated with the stack for a given image build.")
operation GetImageStackEvents {
    input: GetImageStackEventsRequest,
    output: GetStackEventsResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure GetImageStackEventsRequest {
    @httpLabel
    @required
    imageId: ImageId,
    @httpQuery("region")
    region: Region,
    @httpQuery("nextToken")
    nextToken: PaginationToken
}
