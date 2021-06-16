namespace parallelcluster

@documentation("This exception is thrown on an unhandled service error")
@error("server")
@httpError(500)
structure InternalServiceException {
    message: String
}

@documentation("This exception is thrown when a client calls an API with wrong parameters")
@error("client")
@httpError(400)
structure BadRequestException {
    message: String
}

@documentation("This exception is thrown when a client calls the CreateCluster API with an invalid request. This includes an error due to invalid cluster configuration.")
@error("client")
@httpError(400)
structure CreateClusterBadRequestException {
    message: String,
    configurationValidationErrors: ValidationMessages
}

@documentation("This exception is thrown when a client calls the BuildImage API with an invalid request. This includes an error due to invalid image configuration.")
@error("client")
@httpError(400)
structure BuildImageBadRequestException {
    message: String,
    configurationValidationErrors: ValidationMessages
}

@documentation("This exception is thrown when a client calls the UpdateCluster API with an invalid request. This includes an error due to invalid cluster configuration and unsupported update.")
@error("client")
@httpError(400)
structure UpdateClusterBadRequestException {
    message: String,
    configurationValidationErrors: ValidationMessages,
    updateValidationErrors: UpdateErrors,
    changeSet: ChangeSet,
}

list UpdateErrors {
    member: UpdateError
}

structure UpdateError {
    parameter: String,
    currentValue: String,
    requestedValue: String,
    message: String,
}

@documentation("This exception is thrown when the client is not authorized to perform an action")
@error("client")
@httpError(401)
structure UnauthorizedClientError {
    message: String
}

@documentation("This exception is thrown when the requested entity is not found")
@error("client")
@httpError(404)
structure NotFoundException {
    message: String
}

@documentation("This exception is thrown when a client request to create/modify content would result in a conflict")
@error("client")
@httpError(409)
structure ConflictException {
    message: String
}

@documentation("The client is sending more than the allowed number of requests per unit of time.")
@error("client")
@httpError(429)
structure LimitExceededException {
    message: String
}

@documentation("Communicates that the operation would have succeeded without the dryrun flag.")
@error("client")
@httpError(412)
structure DryrunOperationException {
    message: String
}