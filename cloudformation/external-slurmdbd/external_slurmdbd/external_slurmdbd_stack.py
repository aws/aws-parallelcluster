from aws_cdk import CfnParameter, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class ExternalSlurmdbdStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a VPC or select existing VPC
        vpc = ec2.Vpc.from_lookup(self, "PclusterVPC", vpc_id="vpc-0d81e638ed472eacc")

        # Define a CfnParameter for the AMI ID
        ami_id_param = CfnParameter(self, "AmiId", type="String", description="The AMI id for the EC2 instance.")

        # Define the EC2 instance
        instance = ec2.Instance(
            self,
            "MyInstance",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.generic_linux({"us-east-2": ami_id_param.value_as_string}),
            vpc=vpc,
        )

        # Add a secondary private IP to the primary network interface
        secondary_ip_param = CfnParameter(self, "SecondaryPrivateIp", type="String", description="The secondary private IP for the primary network interface.")
        instance.instance.add_property_override(
            "NetworkInterfaces",
            [
                {
                    "DeviceIndex": "0",
                    "AssociatePublicIpAddress": True,
                    "SubnetId": vpc.public_subnets[0].subnet_id,
                    "PrivateIpAddresses": [
                        {
                            "Primary": True,
                            "PrivateIpAddress": "10.0.0.10"
                        },
                        {
                            "Primary": False,
                            "PrivateIpAddress": secondary_ip_param.value_as_string,
                        },
                    ],
                }
            ],
        )

        # Set the removal policy to DESTROY to clean up when the stack is deleted
        instance.apply_removal_policy(RemovalPolicy.DESTROY)
