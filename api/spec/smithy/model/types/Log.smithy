namespace parallelcluster

@documentation("Name of the log stream.")
string LogStreamName


structure LogEvent {
    @required
    @timestampFormat("date-time")
    timestamp: Timestamp,
    @required
    message: String
}

list LogEvents {
    member: LogEvent
}

set LogFilterList {
   member: LogFilterExpression
}

string LogFilterExpression

list LogStreams {
    member: LogStream
}

structure LogStream {
    @required
    @documentation("Name of the log stream.")
    logStreamName: String,
    @required
    @timestampFormat("date-time")
    @documentation("The creation time of the stream.")
    creationTime: Timestamp,
    @required
    @timestampFormat("date-time")
    @documentation("The time of the first event of the stream.")
    firstEventTimestamp: Timestamp,
    @required
    @timestampFormat("date-time")
    @documentation("The time of the last event of the stream. The lastEventTime value updates on an eventual consistency basis. It typically updates in less than an hour from ingestion, but in rare situations might take longer.")
    lastEventTimestamp: Timestamp,
    @required
    @timestampFormat("date-time")
    @documentation("The last ingestion time.")
    lastIngestionTime: Timestamp,
    @required
    @documentation("The sequence token.")
    uploadSequenceToken: String,
    @required
    @documentation("The Amazon Resource Name (ARN) of the log stream.")
    logStreamArn: String,
}

@suppress(["InputOutputStructureReuse"])
structure GetLogEventsResponse {
    nextToken: PaginationToken,
    prevToken: PaginationToken,
    events: LogEvents
}

@suppress(["InputOutputStructureReuse"])
structure ListLogStreamsResponse {
    nextToken: PaginationToken,

    @required
    logStreams: LogStreams,
}


@suppress(["InputOutputStructureReuse"])
structure GetStackEventsResponse {
    nextToken: PaginationToken,
    events: StackEvents
}

structure StackEvent {
    @required
    @documentation("The unique ID name of the instance of the stack.")
    stackId: String,
    @required
    @documentation("The unique ID of this event.")
    eventId: String,
    @required
    @documentation("The name associated with a stack.")
    stackName: String,
    @required
    @documentation("The logical name of the resource specified in the template.")
    logicalResourceId: String,
    @required
    @documentation("The name or unique identifier associated with the physical instance of the resource.")
    physicalResourceId: String,
    @required
    @documentation("Type of resource.")
    resourceType: String,
    @required
    @timestampFormat("date-time")
    @documentation("Time the status was updated.")
    timestamp: Timestamp,
    @required
    @documentation("Current status of the resource.")
    resourceStatus: CloudFormationResourceStatus,

    @documentation("Success/failure message associated with the resource.")
    resourceStatusReason: String,

    @documentation("BLOB of the properties used to create the resource.")
    resourceProperties: String,

    @documentation("The token passed to the operation that generated this event.")
    clientRequestToken: String
}

list StackEvents {
    member: StackEvent
}
