namespace parallelcluster

@readonly
@http(method: "GET", uri: "/v3/images/custom/{imageId}", code: 200)
@tags(["Image Operations"])
@documentation("Get detailed information about an existing image.")
operation DescribeImage {
    input: DescribeImageRequest,
    output: DescribeImageResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure DescribeImageRequest {
    @httpLabel
    @required
    imageId: ImageId,
    @httpQuery("region")
    region: Region,
}

structure DescribeImageResponse {
    @required
    @documentation("Id of the Image to retrieve detailed information for.")
    imageId: String,
    @required
    @documentation("AWS region where the image is created.")
    region: Region,
    @required
    @documentation("ParallelCluster version used to build the image.")
    version: Version,
    @required
    @documentation("Status of the image build.")
    imageBuildStatus: ImageBuildStatus,
    @documentation("ARN of the logs for the image build process.")
    imageBuildLogsArn: String,
    @documentation("Status of the CloudFormation stack for the image build process.")
    cloudformationStackStatus: CloudFormationStackStatus,
    @documentation("Reason for the CloudFormation stack status.")
    cloudformationStackStatusReason: String,
    @documentation("ARN of the main CloudFormation stack.")
    cloudformationStackArn: String,
    @documentation("Timestamp representing the image creation time.")
    @timestampFormat("date-time")
    creationTime: Timestamp,
    @documentation("Timestamp representing the CloudFormation stack creation time.")
    @timestampFormat("date-time")
    cloudformationStackCreationTime: Timestamp,
    @documentation("Tags for the CloudFormation stack.")
    cloudformationStackTags: Tags,
    @required
    @documentation("Configuration for the image build process.")
    imageConfiguration: ImageConfigurationStructure,
    @documentation("Status of the ImageBuilder Image resource.")
    imagebuilderImageStatus: ImageBuilderImageStatus,
    @documentation("Reason for the ImageBuilder Image status.")
    imagebuilderImageStatusReason: String,
    // ImageBuilderImageArn or ImageBuilderImageInfo structure
    @documentation("EC2 ami information.")
    ec2AmiInfo: Ec2AmiInfo,
}
