namespace parallelcluster

@paginated
@readonly
@http(method: "GET", uri: "/v3/images/custom", code: 200)
@tags(["Image Operations"])
@documentation("Retrieve the list of existing custom images managed by the API. Deleted images are not showed by default")
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
    @documentation("List Images built into a given AWS Region. Defaults to the AWS region the API is deployed to.")
    region: Region,
    @httpQuery("nextToken")
    nextToken: PaginationToken,
    @httpQuery("imageStatus")
    @documentation("Filter by image status.")
    imageStatus: ImageStatusFilteringOptions,
}

structure ListImagesResponse {
    nextToken: PaginationToken,

    @required
    items: ImageInfoSummaries,
}

list ImageInfoSummaries {
    member: ImageInfoSummary
}

set ImageStatusFilteringOptions {
    member: ImageBuildStatus
}
