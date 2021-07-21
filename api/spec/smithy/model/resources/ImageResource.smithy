namespace parallelcluster

resource OfficialImage {
    operations: [DescribeOfficialImages]
}

resource CustomImage {
    identifiers: { imageId: ImageId },
    put: BuildImage,
    list: ListImages,
    read: DescribeImage,
    delete: DeleteImage,
}
