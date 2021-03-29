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
    ]
}

structure BuildImageRequest {
    @httpQuery("suppressValidators")
    @documentation("Identifies one or more config validators to suppress. Format: ALL|id:$value|level:(info|error|warning)|type:$value")
    suppressValidators: SuppressValidatorsList,
    @httpQuery("validationFailureLevel")
    @documentation("Min validation level that will cause the creation to fail. Defaults to 'error'.")
    validationFailureLevel: ValidationLevel,
    @httpQuery("dryrun")
    @documentation("Only perform request validation without creating any resource. It can be used to validate the image configuration. Response code: 200")
    dryrun: Boolean,
    @httpQuery("rollbackOnFailure")
    @documentation("When set it automatically initiates an image stack rollback on failures. Defaults to true.")
    rollbackOnFailure: Boolean,
    @idempotencyToken
    @httpQuery("clientToken")
    @documentation("Idempotency token that can be set by the client so that retries for the same request are idempotent")
    clientToken: String,

    @required
    name: ImageName,
    region: Region,
    @required
    imageConfiguration: ImageConfigurationData,
}

structure BuildImageResponse {
    @required
    image: ImageInfoSummary,
    @required
    @documentation("List of messages collected during image config validation whose level is lower than the validationFailureLevel set by the user")
    validationMessages: ValidationMessages
}

list SuppressValidatorsList {
   member: SuppressValidatorExpression
}

string SuppressValidatorExpression
