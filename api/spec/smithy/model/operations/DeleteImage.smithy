namespace parallelcluster

@http(method: "DELETE", uri: "/v3/images/custom/{imageName}", code: 202)
@tags(["Image Operations"])
@idempotent
@documentation("Initiate the deletion of the custom ParallelCluster image.")
operation DeleteImage {
    input: DeleteImageRequest,
    output: DeleteImageResponse,
    errors: [
      InternalServiceException,
      BadRequestException,
      NotFoundException,
      UnauthorizedClientError,
      LimitExceededException,
    ]
}

structure DeleteImageRequest {
    @httpLabel
    @required
    imageName: ImageName,

    @httpQuery("region")
    region: Region,
    @idempotencyToken
    @httpQuery("clientToken")
    @documentation("Idempotency token that can be set by the client so that retries for the same request are idempotent")
    clientToken: String,
    @httpQuery("force")
    @documentation("Force deletion in case there are instances using the AMI or in case the AMI is shared")
    force: Boolean,
}

structure DeleteImageResponse {
    @required
    image: ImageInfoSummary
}
