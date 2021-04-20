from pcluster.aws.common import AWSExceptionHandler, Boto3Client


class ImageBuilderClient(Boto3Client):
    """Imagebuilder Boto3 client."""

    def __init__(self):
        super().__init__("imagebuilder")

    @AWSExceptionHandler.handle_client_exception
    def get_image_resources(self, image_arn):
        """Get image info by ami arn."""
        return self._client.get_image(imageBuildVersionArn=image_arn)

    @AWSExceptionHandler.handle_client_exception
    def get_image_id(self, image_arn):
        """Retrieve image id by image arn."""
        ami_list = self.get_image_resources(image_arn).get("image", []).get("outputResources", []).get("amis", [])
        return ami_list[0].get("image") if ami_list else None
