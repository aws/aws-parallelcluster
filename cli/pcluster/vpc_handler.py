import boto3
import functools

from botocore.exceptions import ClientError, BotoCoreError


class VpcHandler:
    """
    This class handles vpc automation related to pcluster.
    """

    @staticmethod
    def handle_client_exception(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (BotoCoreError, ClientError) as e:
                raise RuntimeError(e.response["Error"]["Message"])

        return wrapper

    @handle_client_exception
    def __init__(self, aws_region_name):
        """
        Inizialize the VpcHandler with the specified region

        :param aws_region_name: the region in which you want to use the VpcHandler
        """
        self.client = boto3.client("ec2", region_name=aws_region_name)
        self.ec2 = boto3.resource("ec2", region_name=aws_region_name)

    @handle_client_exception
    def create(self):
        """
        Create a vpc for the given region name.

        :return: the id of the created vpc
        :raise RuntimeError: if some problems occurred during vpc creation
        """
        response = self.client.create_vpc(CidrBlock='10.0.0.0/16')
        return response["Vpc"]["VpcId"]

    @handle_client_exception
    def set(self, vpc_id, name=None):
        """
        Sets the parameter necessary for a vpc to be pcluster-compatible.

        :param vpc_id: the target vpc_id
        :param name: the name that you want to give to the vpc
        :raise RuntimeError: if some problems occurred during the operation
        """
        vpc = self.ec2.Vpc(vpc_id)
        if name is not None:
            self.ec2.create_tags(Resources=[vpc_id], Tags=[{"Key": "Name", "Value": name}])
        vpc.modify_attribute(EnableDnsHostnames={"Value": True})
        vpc.modify_attribute(EnableDnsSupport={"Value": True})

    @handle_client_exception
    def check(self, vpc_id):
        """
        Check whether the given vpc respects the condition needed for pcluster.

        :param vpc_id: the target vpc_id
        :return: True if the vpc is pcluster compatible
        :raise RuntimeError: if some problems occurred during the operation
        """
        vpc = self.ec2.Vpc(vpc_id)
        dns_resolution = vpc.describe_attribute(Attribute="enableDnsSupport")["EnableDnsSupport"]["Value"]
        dns_hostnames = vpc.describe_attribute(Attribute="enableDnsHostnames")["EnableDnsHostnames"]["Value"]
        return dns_resolution and dns_hostnames and vpc.dhcp_options_id != "default"

