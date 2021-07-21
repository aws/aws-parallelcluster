namespace parallelcluster

@http(method: "POST", uri: "/v3/images/custom", code: 202)
@tags(["Image Operations"])
@documentation("Create a custom ParallelCluster image in a given region.")
@idempotent
operation BuildImage {
    input: BuildImageRequest,
    output: BuildImageResponse,
    errors: [
      InternalServiceException,
      BuildImageBadRequestException,
      ConflictException,
      UnauthorizedClientError,
      LimitExceededException,
      DryrunOperationException,
    ]
}

structure BuildImageRequest {
    @httpQuery("suppressValidators")
    @documentation("Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+)")
    suppressValidators: SuppressValidatorsList,
    @httpQuery("validationFailureLevel")
    @documentation("Min validation level that will cause the creation to fail. (Defaults to 'ERROR'.)")
    validationFailureLevel: ValidationLevel,
    @httpQuery("dryrun")
    @documentation("Only perform request validation without creating any resource. It can be used to validate the image configuration.")
    dryrun: Boolean,
    @httpQuery("rollbackOnFailure")
    @documentation("When set, will automatically initiate an image stack rollback on failure. (Defaults to true.)")
    rollbackOnFailure: Boolean,
    @httpQuery("region")
    region: Region,

    @required
    imageConfiguration: ImageConfigurationData,

    @required
    @documentation("Id of the Image that will be built.")
    imageId: ImageId,
}

structure BuildImageResponse {
    @required
    image: ImageInfoSummary,
    @documentation("List of messages collected during image config validation whose level is lower than the 'validationFailureLevel' set by the user.")
    validationMessages: ValidationMessages
}
