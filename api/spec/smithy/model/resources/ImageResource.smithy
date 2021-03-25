namespace parallelcluster

resource OfficialImage {
    operations: [DescribeOfficialImages]
}

resource CustomImage {
    identifiers: { imageName: ImageName },
    create: BuildImage,
    list: ListImages,
    read: DescribeImage,
    delete: DeleteImage,
}
