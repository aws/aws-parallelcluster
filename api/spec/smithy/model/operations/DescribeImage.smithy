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
    @documentation("Id of the Image")
    imageId: String,
    @required
    @documentation("AWS region where the image is created")
    region: Region,
    @required
    @documentation("ParallelCluster version used to build the image")
    version: Version,
    @required
    @documentation("Status of the image build.")
    imageBuildStatus: ImageBuildStatus,
    @required
    @documentation("Status of the CloudFormation stack for the image build process.")
    cloudformationStackStatus: CloudFormationStatus,
    @required
    @documentation("ARN of the main CloudFormation stack")
    cloudformationStackArn: String,
    @required
    @documentation("Timestamp representing the image creation time")
    @timestampFormat("date-time")
    creationTime: Timestamp,
    @required
    @documentation("Configuration for the image build process")
    imageConfiguration: ImageConfigurationStructure,
    @required
    @documentation("Tags of the infrastructure to build the Image")
    tags: Tags,
    @documentation("Status of the ImageBuilder Image resource for the image build process.")
    imagebuilderImageStatus: ImageBuilderImageStatus,
    // ImageBuilderImageArn or ImageBuilderImageInfo structure
    @documentation("EC2 ami info")
    ec2AmiInfo: Ec2AmiInfo,
    @documentation("Describe the reason of the failure when the stack is in CREATE_FAILED, UPDATE_FAILED or DELETE_FAILED status")
    failureReason: String,
}
