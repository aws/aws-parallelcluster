namespace parallelcluster

@suppress(["MissingPaginatedTrait"])
@readonly
@http(method: "GET", uri: "/v3/images/official", code: 200)
@tags(["Image Operations"])
@documentation("List Official ParallelCluster AMIs.")
operation ListOfficialImages {
    input: ListOfficialImagesRequest,
    output: ListOfficialImagesResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure ListOfficialImagesRequest {
    @httpQuery("region")
    region: Region,
    @httpQuery("os")
    @documentation("Filter by OS distribution (Default is to not filter.)")
    os: String,
    @httpQuery("architecture")
    @documentation("Filter by architecture (Default is to not filter.)")
    architecture: String,
}

structure ListOfficialImagesResponse {
    @required
    images: AmisInfo,
}

list AmisInfo {
    member: AmiInfo
}

structure AmiInfo {
    @required
    architecture: String,
    @required
    amiId: String,
    @required
    name: String,
    @required
    os: String,
    @required
    version: Version,
}
