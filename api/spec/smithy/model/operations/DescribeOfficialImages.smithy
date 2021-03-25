namespace parallelcluster

@readonly
@http(method: "GET", uri: "/v3/images/official", code: 200)
@tags(["Image Operations"])
@documentation("Describe ParallelCluster AMIs.")
@paginated
operation DescribeOfficialImages {
    input: DescribeOfficialImagesRequest,
    output: DescribeOfficialImagesResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure DescribeOfficialImagesRequest {
    @httpQuery("version")
    @documentation("ParallelCluster version to retrieve AMIs for.")
    version: Version,
    @httpQuery("region")
    region: Region,
    @httpQuery("os")
    @documentation("Filter by OS distribution")
    os: String,
    @httpQuery("architecture")
    @documentation("Filter by architecture")
    architecture: String,
    @httpQuery("nextToken")
    nextToken: PaginationToken,
}

structure DescribeOfficialImagesResponse {
    nextToken: PaginationToken,

    @required
    items: AmisInfo,
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
}
