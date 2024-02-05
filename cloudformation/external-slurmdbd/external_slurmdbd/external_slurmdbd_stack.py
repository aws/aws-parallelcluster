import hashlib
import json

import pkg_resources
from aws_cdk import CfnOutput, CfnParameter, Fn, Stack
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_s3 as s3
from constructs import Construct


def get_user_data_content(user_data_path: str):
    """Retrieve user data content."""
    user_data_file_path = pkg_resources.resource_filename(__name__, user_data_path)
    with open(user_data_file_path, "r", encoding="utf-8") as user_data_file:
        user_data_content = user_data_file.read()
    return user_data_content


EXTERNAL_SLURMDBD_ASG_SIZE = "1"


def get_assume_role_policy_document(service: str):
    """Return default service assume role policy document."""
    return iam.PolicyDocument(
        statements=[
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal(service=service)],
            )
        ]
    )


class ExternalSlurmdbdStack(Stack):
    """Create the CloudFormation stack template for External Slurmdbd."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # define networking stuff
        self.vpc_id = CfnParameter(
            self, "VPCId", type="String", description="The VPC to be used for the Slurmdbd stack."
        )

        self.subnet_id = CfnParameter(
            self, "SubnetId", type="AWS::EC2::Subnet::Id", description="The Subnet to be used for the Slurmdbd stack."
        )

        # Define additional CloudFormation parameters for dna.json to pass to cookbook
        self.dbms_uri = CfnParameter(self, "DBMSUri", type="String", description="DBMS URI for Slurmdbd.")
        self.dbms_username = CfnParameter(
            self, "DBMSUsername", type="String", description="DBMS Username for Slurmdbd."
        )
        self.dbms_password_secret_arn = CfnParameter(
            self, "DBMSPasswordSecretArn", type="String", description="Secret ARN for DBMS password."
        )
        self.dbms_database_name = CfnParameter(
            self, "DBMSDatabaseName", type="String", description="DBMS Database Name for Slurmdbd."
        )
        self.munge_key_secret_arn = CfnParameter(
            self, "MungeKeySecretArn", type="String", description="Secret ARN for Munge key."
        )
        self.custom_cookbook_url_param = CfnParameter(
            self, "CustomCookbookUrl", type="String", description="URL of the custom Chef Cookbook.", default=""
        )

        # create management security group with SSH access from anywhere (TEMPORARY!)
        self._ssh_server_sg, self._ssh_client_sg = self._add_management_security_groups()

        # create a pair of security groups for the slurm accounting traffic across
        # between cluster head node and external slurmdbd instance via port 6819
        self._slurmdbd_server_sg, self._slurmdbd_client_sg = self._add_slurmdbd_accounting_security_groups()

        # Create a CloudWatch log group
        self._log_group = self._add_cloudwatch_log_group()

        # add S3 bucket to store the slurmdbd configuration
        self.s3_bucket = self._add_s3_bucket()

        # define IAM role and necessary IAM policies
        self._role = self._add_iam_role()

        self._instance_profile = self._add_instance_profile(self._role.ref, "ExternalSlurmdbdInstanceProfile")

        # create Launch Template
        # This defines the dna.json and so it depends on many of the previous steps.
        # It should be launched just before the ASG that should be the last before the outputs.
        self._launch_template = self._add_external_slurmdbd_launch_template()

        # define EC2 Auto Scaling Group (ASG)
        self._external_slurmdbd_asg = self._add_external_slurmdbd_auto_scaling_group()

        # define Primary Slurmdbd Instance (not via ASG)
        # self._primary_slurmdbd_instance = self._add_slurmdbd_primary_instance()

        # define external slurmdbd hosted zone
        # self._hosted_zone = self._add_hosted_zone()

        # Add DNS record to hosted zone
        # self._add_instance_to_dns(
        #     ip_addr=self._primary_slurmdbd_instance.attr_private_ip,
        #     name="slurmdbd",
        # )

        self._add_outputs()

    def _add_cfn_init_config(self):
        dna_json_content = {
            "slurmdbd_ip": self.slurmdbd_private_ip.value_as_string,
            "slurmdbd_port": self.slurmdbd_port.value_as_number,
            "dbms_uri": self.dbms_uri.value_as_string,
            "dbms_username": self.dbms_username.value_as_string,
            "dbms_database_name": self.dbms_database_name.value_as_string,
            "dbms_password_secret_arn": self.dbms_password_secret_arn.value_as_string,
            "munge_key_secret_arn": self.munge_key_secret_arn.value_as_string,
            "region": self.region,
            "log_group_name": self._log_group.log_group_name,
            "stack_name": self.stack_name,
            "is_external_slurmdbd": True,
            "slurmdbd_conf_bucket": self.s3_bucket.bucket_name,
        }

        return {
            "configSets": {"default": ["setup", "configure"]},
            "setup": {
                "files": {
                    "/etc/chef/dna.json": {
                        "content": json.dumps(dna_json_content),
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                    }
                },
                "commands": {
                    "chef": {
                        "command": (
                            "cinc-client --local-mode --config /etc/chef/client.rb --log_level info "
                            "--logfile /var/log/chef-client.log --force-formatter --no-color "
                            "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json "
                            "--override-runlist aws-parallelcluster-entrypoints::external_slurmdbd_config"
                        ),
                        "cwd": "/etc/chef",
                    }
                },
            },
            # TODO: delete the cfn-hup hook
            "configure": {
                "files": {
                    "/etc/cfn/hooks.d/cfn-auto-reloader.conf": {
                        "content": Fn.sub(
                            "[cfn-auto-reloader-hook]\n"
                            "triggers=post.update\n"
                            "path=Resources.LaunchTemplate.Metadata.AWS::CloudFormation::Init\n"
                            "action=/usr/bin/echo 'I was triggered by a change in AWS::CloudFormation::Init metadata!' > /tmp/cfn_init_metadata_update.log\n"  # noqa: E501
                            "runas=root\n"
                        ),
                        "mode": "000400",
                        "owner": "root",
                        "group": "root",
                    },
                    "/etc/cfn/cfn-hup.conf": {
                        "content": Fn.sub(
                            "[main]\n" "stack=${StackId}\n" "region=${Region}\n" "interval=2\n",
                            {
                                "StackId": self.stack_id,
                                "Region": self.region,
                            },
                        ),
                        "mode": "000400",
                        "owner": "root",
                        "group": "root",
                    },
                }
            },
        }

    def _add_management_security_groups(self):
        server_sg = ec2.CfnSecurityGroup(
            self,
            "SSHServerSecurityGroup",
            group_description="Allow SSH access to slurmdbd instance (server)",
            vpc_id=self.vpc_id.value_as_string,
        )

        client_sg = ec2.CfnSecurityGroup(
            self,
            "SSHClientSecurityGroup",
            group_description="Allow SSH access to slurmdbd instance (client)",
            vpc_id=self.vpc_id.value_as_string,
        )

        ec2.CfnSecurityGroupIngress(
            self,
            "Allow SSH access from client SG",
            ip_protocol="tcp",
            from_port=22,
            to_port=22,
            source_security_group_id=client_sg.ref,
            group_id=server_sg.ref,
        )

        return server_sg, client_sg

    # FIXME: make the ingress rules more configurable
    def _add_slurmdbd_accounting_security_groups(self):
        slurmdbd_server_sg = ec2.CfnSecurityGroup(
            self,
            "SlurmdbdServerSecurityGroup",
            group_description="Allow Slurm accounting traffic to the slurmdbd instance (server)",
            vpc_id=self.vpc_id.value_as_string,
        )

        slurmdbd_client_sg = ec2.CfnSecurityGroup(
            self,
            "SlurmdbdClientSecurityGroup",
            group_description="Allow Slurm accounting traffic from the cluster head node (client)",
            vpc_id=self.vpc_id.value_as_string,
        )

        self.slurmdbd_port = CfnParameter(
            self,
            "SlurmdbdPort",
            type="Number",
            description="The port the slurmdbd service listens to.",
            default=6819,
        )

        ec2.CfnSecurityGroupIngress(
            self,
            "Allow Slurm accounting traffic from the cluster head node",
            ip_protocol="tcp",
            from_port=self.slurmdbd_port.value_as_number,
            to_port=self.slurmdbd_port.value_as_number,
            source_security_group_id=slurmdbd_client_sg.ref,
            group_id=slurmdbd_server_sg.ref,
        )

        ec2.CfnSecurityGroupIngress(
            self,
            "Allow traffic coming from slurmdbd instance",
            ip_protocol="tcp",
            from_port=6820,
            to_port=6829,
            source_security_group_id=slurmdbd_server_sg.ref,
            group_id=slurmdbd_client_sg.ref,
        )

        return slurmdbd_server_sg, slurmdbd_client_sg

    def _add_instance_profile(self, role_ref: str, name: str):
        return iam.CfnInstanceProfile(
            self,
            name,
            roles=[role_ref],
        ).ref

    def _add_external_slurmdbd_launch_template(self):
        # Define a CfnParameter for the AMI ID
        # This AMI should be Parallel Cluster AMI, which has installed Slurm and related software
        ami_id_param = CfnParameter(
            self, "AmiId", type="AWS::EC2::Image::Id", description="The AMI id for the EC2 instance."
        )
        instance_type_param = CfnParameter(
            self,
            "InstanceType",
            type="String",
            description="The instance type for the EC2 instance",
        )
        key_name_param = CfnParameter(
            self,
            "KeyName",
            type="AWS::EC2::KeyPair::KeyName",
            description="The SSH key name to access the instance (for management purposes only)",
        )
        self.slurmdbd_private_ip = CfnParameter(
            self,
            "PrivateIp",
            type="String",
            description="Static private IP address + prefix to assign to the slurmdbd instance",
        )
        self.slurmdbd_private_prefix = CfnParameter(
            self,
            "PrivatePrefix",
            type="String",
            description="Subnet prefix to assign with the private IP to the slurmdbd instance",
        )
        dbms_client_sg_id = CfnParameter(
            self, "DBMSClientSG", type="AWS::EC2::SecurityGroup::Id", description="DBMS Client Security Group Id"
        )

        launch_template_data = ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
            key_name=key_name_param.value_as_string,
            image_id=ami_id_param.value_as_string,
            instance_type=instance_type_param.value_as_string,
            user_data=Fn.base64(
                Fn.sub(
                    get_user_data_content("../resources/user_data.sh"),
                    {
                        **{
                            "CustomCookbookUrl": self.custom_cookbook_url_param.value_as_string,
                            "StackName": self.stack_name,
                            "Region": self.region,
                            "PrivateIp": self.slurmdbd_private_ip.value_as_string,
                            "SubnetPrefix": self.slurmdbd_private_prefix.value_as_string,
                        },
                    },
                )
            ),
            iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(name=self._instance_profile),
            network_interfaces=[
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=0,
                    groups=[
                        self._ssh_server_sg.ref,
                        self._slurmdbd_server_sg.ref,
                        dbms_client_sg_id.value_as_string,
                    ],
                    subnet_id=self.subnet_id.value_as_string,
                ),
            ],
            metadata_options=ec2.CfnLaunchTemplate.MetadataOptionsProperty(
                http_tokens="required",
            ),
        )

        launch_template = ec2.CfnLaunchTemplate(self, "LaunchTemplate", launch_template_data=launch_template_data)

        self._cfn_init_config = self._add_cfn_init_config()
        launch_template.add_metadata("AWS::CloudFormation::Init", self._cfn_init_config)

        return launch_template

    def _add_slurmdbd_primary_instance(self):
        return ec2.CfnInstance(
            self,
            id="ExternalSlurmdbdPrimaryInstance",
            launch_template=ec2.CfnInstance.LaunchTemplateSpecificationProperty(
                version=self._launch_template.attr_latest_version_number, launch_template_id=self._launch_template.ref
            ),
        )

    def _add_external_slurmdbd_auto_scaling_group(self):
        return autoscaling.CfnAutoScalingGroup(
            self,
            "External-Slurmdbd-ASG",
            max_size=EXTERNAL_SLURMDBD_ASG_SIZE,
            min_size=EXTERNAL_SLURMDBD_ASG_SIZE,
            desired_capacity=EXTERNAL_SLURMDBD_ASG_SIZE,
            launch_template=autoscaling.CfnAutoScalingGroup.LaunchTemplateSpecificationProperty(
                version=self._launch_template.attr_latest_version_number, launch_template_id=self._launch_template.ref
            ),
            vpc_zone_identifier=[self.subnet_id.value_as_string],
        )

    def _add_iam_role(self):
        role = iam.CfnRole(
            self,
            "SlurmdbdInstanceRole",
            assume_role_policy_document=get_assume_role_policy_document("ec2.{0}".format(self.url_suffix)),
            description="Role for Slurmdbd EC2 instance to access necessary AWS resources",
        )

        iam.CfnPolicy(
            Stack.of(self),
            "ExternalSlurmdbdPolicies",
            policy_name="ExternalSlurmdbdPolicies",
            roles=[role.ref],
            policy_document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=["secretsmanager:GetSecretValue"],
                        resources=[
                            self.dbms_password_secret_arn.value_as_string,
                            self.munge_key_secret_arn.value_as_string,
                        ],
                        effect=iam.Effect.ALLOW,
                        sid="SecretsManagerPolicy",
                    ),
                    iam.PolicyStatement(
                        actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                        resources=[self._log_group.log_group_arn],
                        effect=iam.Effect.ALLOW,
                        sid="CloudWatchLogsPolicy",
                    ),
                    iam.PolicyStatement(
                        actions=["ec2:AssignPrivateIpAddresses"],
                        resources=["*"],
                        effect=iam.Effect.ALLOW,
                        conditions={"StringLike": {"ec2:Subnet": f"*{self.subnet_id.value_as_string}"}},
                        sid="IPAssignmentPolicy",
                    ),
                    iam.PolicyStatement(
                        actions=[
                            "s3:ListBucket",
                        ],
                        resources=[self.s3_bucket.attr_arn],
                        effect=iam.Effect.ALLOW,
                        sid="S3BucketPolicy",
                    ),
                    iam.PolicyStatement(
                        actions=[
                            "s3:GetObject",
                            "s3:PutObject",
                            "s3:AbortMultipartUpload",
                            "s3:DeleteObject",
                        ],
                        resources=[self.s3_bucket.attr_arn + "/*"],
                        effect=iam.Effect.ALLOW,
                        sid="S3BucketObjectsPolicy",
                    ),
                    # iam.PolicyStatement(
                    #     actions=[
                    #         "route53:CreateHostedZone",
                    #         "route53:DeleteHostedZone",
                    #     ],
                    #     resources=[slurmdbd_hosted_zone.value_as_string],
                    #     effect=iam.Effect.ALLOW,
                    #     sid="IPAssignmentPolicy",
                    # ),
                ]
            ),
        )

        return role

    def _add_cloudwatch_log_group(self):
        # Create a new CloudWatch log group
        return logs.LogGroup(
            self,
            "SlurmdbdLogGroup",
            log_group_name=Fn.join(
                "-",
                [
                    f"/aws/parallelcluster/external-slurmdbd/{self.stack_name}",
                    Fn.select(4, Fn.split("-", Fn.select(2, Fn.split("/", self.stack_id)))),
                ],
            ),
            retention=logs.RetentionDays.ONE_WEEK,
        )

    def _add_s3_bucket(self):
        return s3.CfnBucket(
            self,
            id="ExternalSlurmdbdS3Bucket",
            bucket_name=self.stack_name.lower() + "-" + hashlib.sha256((self.account + self.region).encode()).hexdigest()[0:16],
            public_access_block_configuration=s3.CfnBucket.PublicAccessBlockConfigurationProperty(
                block_public_acls=True,
                block_public_policy=True,
                ignore_public_acls=True,
                restrict_public_buckets=True,
            ),
            versioning_configuration=s3.CfnBucket.VersioningConfigurationProperty(status="Enabled"),
        )

    def _add_hosted_zone(self):
        return route53.CfnHostedZone(
            self,
            id="ExternalSlurmdbdHostedZone",
            name="externalslurmdbdhostedzone",
            vpcs=[
                route53.CfnHostedZone.VPCProperty(
                    vpc_id=self.vpc_id.value_as_string,
                    vpc_region=self.region,
                )
            ],
        )

    def _add_instance_to_dns(self, ip_addr, name):
        route53.CfnRecordSet(
            self,
            "ExternalSlurmdbdRecordSet",
            name=(name + "." + self._hosted_zone.name),
            type="A",
            hosted_zone_id=self._hosted_zone.attr_id,
            region=self.region,
            resource_records=[ip_addr],
            set_identifier="externalslurmdbdsetidentifier",
            ttl="300",
        )

    def _add_outputs(self):
        CfnOutput(
            self,
            "SlurmdbdPrivateIp",
            description="Secondary Private IP Address of the slurmdbd instance",
            value=self.slurmdbd_private_ip.value_as_string,
        )
        CfnOutput(
            self,
            "SlurmdbdPortOutput",
            description="Port used to connect to slurmdbd service",
            key="SlurmdbdPort",
            value=self.slurmdbd_port.value_as_string,
        )
        CfnOutput(
            self,
            "AccountingClientSecurityGroup",
            description="Security Group ID that allows traffic from the slurmctld to slurmdbd",
            value=self._slurmdbd_client_sg.ref,
        )
        CfnOutput(
            self,
            "SshClientSecurityGroup",
            description="Security Group ID that allows SSH traffic from the HeadNode to slurmdbd instance",
            value=self._ssh_client_sg.ref,
        )
        CfnOutput(
            self,
            "SlurmdbdConfigS3BucketName",
            description="S3 Bucket where a copy of the slurmdbd configuration files can be stored and re-used when "
            "re-provisioning the slurmdbd instance",
            value=self.s3_bucket.bucket_name,
        )
