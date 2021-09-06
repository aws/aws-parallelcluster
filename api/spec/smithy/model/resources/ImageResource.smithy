namespace parallelcluster

resource OfficialImage {
    operations: [ListOfficialImages]
}

resource CustomImage {
    identifiers: { imageId: ImageId },
    put: BuildImage,
    list: ListImages,
    read: DescribeImage,
    delete: DeleteImage,
}

resource ImageLogStream {
    identifiers: { imageId: ImageId, logStreamName: LogStreamName },
    list: ListImageLogStreams,
    read: GetImageLogEvents
}

resource ImageStackEvents {
    identifiers: { imageId: ImageId},
    read: GetImageStackEvents
}
