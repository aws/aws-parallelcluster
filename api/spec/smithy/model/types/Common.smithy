namespace parallelcluster

@documentation("AWS Region. Defaults to the region the API is deployed to.")
string Region

string Version

@documentation("Token to use for paginated requests.")
string PaginationToken

list Tags {
    member: Tag
}

structure Tag {
    @documentation("Tag name")
    key: String,
    @documentation("Tag value")
    value: String,
}

structure ConfigValidationMessage {
    @documentation("Id of the validator")
    id: String,
    @documentation("Type of the validator")
    type: String,
    @documentation("Validation level")
    level: ValidationLevel,
    @documentation("Validation message")
    message: String,
}

list ValidationMessages {
    member: ConfigValidationMessage
}

@enum([
    {name: "INFO", value: "INFO"},
    {name: "WARNING", value: "WARNING"},
    {name: "ERROR", value: "ERROR"},
])
string ValidationLevel

@enum([
    {name: "CREATE_IN_PROGRESS", value: "CREATE_IN_PROGRESS"},
    {name: "CREATE_FAILED", value: "CREATE_FAILED"},
    {name: "CREATE_COMPLETE", value: "CREATE_COMPLETE"},
    {name: "ROLLBACK_IN_PROGRESS", value: "ROLLBACK_IN_PROGRESS"},
    {name: "ROLLBACK_FAILED", value: "ROLLBACK_FAILED"},
    {name: "ROLLBACK_COMPLETE", value: "ROLLBACK_COMPLETE"},
    {name: "DELETE_IN_PROGRESS", value: "DELETE_IN_PROGRESS"},
    {name: "DELETE_FAILED", value: "DELETE_FAILED"},
    {name: "DELETE_COMPLETE", value: "DELETE_COMPLETE"},
    {name: "UPDATE_IN_PROGRESS", value: "UPDATE_IN_PROGRESS"},
    {name: "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS", value: "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"},
    {name: "UPDATE_COMPLETE", value: "UPDATE_COMPLETE"},
    {name: "UPDATE_ROLLBACK_IN_PROGRESS", value: "UPDATE_ROLLBACK_IN_PROGRESS"},
    {name: "UPDATE_ROLLBACK_FAILED", value: "UPDATE_ROLLBACK_FAILED"},
    {name: "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS", value: "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS"},
    {name: "UPDATE_ROLLBACK_COMPLETE", value: "UPDATE_ROLLBACK_COMPLETE"}
])
string CloudFormationStatus
