namespace parallelcluster

@readonly
@http(method: "GET", uri: "/v3/images/official", code: 200)
@tags(["Image Operations"])
@documentation("Describe ParallelCluster AMIs.")
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
}

structure DescribeOfficialImagesResponse {
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
