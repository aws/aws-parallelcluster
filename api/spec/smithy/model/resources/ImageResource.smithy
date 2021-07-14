namespace parallelcluster

resource OfficialImage {
    operations: [DescribeOfficialImages]
}

resource CustomImage {
    identifiers: { imageId: ImageId },
    create: BuildImage,
    list: ListImages,
    read: DescribeImage,
    delete: DeleteImage,
}
