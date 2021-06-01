namespace parallelcluster

@suppress(["MissingPaginatedTrait"])
// FIXME We unroll the describe_stacks pagination due to potential inconsistency in the transition (i.e. when the stack has
// produced an image is becomes DELETE_IN_PROGRESS we could have it both in the describe_images and describe_stacks, and
// depending on how we chose to handle the issue we could either return the same image twice in different pages, or ignore
// the describe stack data and risk never returning the data for the image, in case it was not present in the first page
// describe_images ImageInfoSummaries -the results of the describe_images vary across calls, and we cannot return them
// multiple times, or we would have repetitions in different pages-)
//@paginated
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
    //@httpQuery("nextToken")
    //nextToken: PaginationToken,
    @httpQuery("imageStatus")
    @documentation("Filter by image status.")
    imageStatus: ImageStatusFilteringOptions,
}

structure ListImagesResponse {
    //nextToken: PaginationToken,

    @required
    items: ImageInfoSummaries,
}

list ImageInfoSummaries {
    member: ImageInfoSummary
}

@enum([
    {name: "BUILD_IN_PROGRESS", value: "BUILD_IN_PROGRESS"},
    {name: "BUILD_FAILED", value: "BUILD_FAILED"},
    {name: "BUILD_COMPLETE", value: "BUILD_COMPLETE"},
    {name: "DELETE_IN_PROGRESS", value: "DELETE_IN_PROGRESS"},
    {name: "DELETE_FAILED", value: "DELETE_FAILED"},
])
string ImageStatusFilteringOption

set ImageStatusFilteringOptions {
    member: ImageStatusFilteringOption
}
