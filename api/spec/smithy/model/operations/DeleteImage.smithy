namespace parallelcluster

@http(method: "DELETE", uri: "/v3/images/custom/{imageId}", code: 202)
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
    imageId: ImageId,

    @httpQuery("region")
    region: Region,
    @httpQuery("force")
    @documentation("Force deletion in case there are instances using the AMI or in case the AMI is shared. (Defaults to 'false'.)")
    force: Boolean,
}

structure DeleteImageResponse {
    @required
    image: ImageInfoSummary
}
