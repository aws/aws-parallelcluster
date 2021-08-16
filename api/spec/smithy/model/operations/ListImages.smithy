namespace parallelcluster

@suppress(["MissingPaginatedTrait"])
@paginated
@readonly
@http(method: "GET", uri: "/v3/images/custom", code: 200)
@tags(["Image Operations"])
@documentation("Retrieve the list of existing custom images.")
operation ListImages {
    input: ListImagesRequest,
    output: ListImagesResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure ListImagesRequest {
    @httpQuery("region")
    @documentation("List images built in a given AWS Region.")
    region: Region,
    @httpQuery("nextToken")
    nextToken: PaginationToken,
    @required
    @httpQuery("imageStatus")
    @documentation("Filter images by the status provided.")
    imageStatus: ImageStatusFilteringOption,
}

structure ListImagesResponse {
    nextToken: PaginationToken,

    @required
    images: ImageInfoSummaries,
}

list ImageInfoSummaries {
    member: ImageInfoSummary
}

@enum([
    {name: "AVAILABLE", value: "AVAILABLE"},
    {name: "PENDING", value: "PENDING"},
    {name: "FAILED", value: "FAILED"},
])
string ImageStatusFilteringOption
