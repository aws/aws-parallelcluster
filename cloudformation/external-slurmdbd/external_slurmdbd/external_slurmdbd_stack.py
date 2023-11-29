import json
import os

from aws_cdk import CfnParameter, Fn, Stack
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from constructs import Construct
import pkg_resources


def get_user_data_content(user_data_path: str):
    """Retrieve user data content."""
    user_data_file_path = pkg_resources.resource_filename(__name__, user_data_path)
    with open(user_data_file_path, "r", encoding="utf-8") as user_data_file:
        user_data_content = user_data_file.read()
    return user_data_content


EXTERNAL_SLURMDBD_ASG_SIZE = "1"


class ExternalSlurmdbdStack(Stack):
    """Create the CloudFormation stack template for External Slurmdbd."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # define networking stuff
        self.vpc_id = CfnParameter(
            self, "VPCId", type="String", description="The VPC to be used for the Slurmdbd stack."
        )

        self.vpc = ec2.Vpc.from_vpc_attributes(
            self,
            "Vpc",
            vpc_id=self.vpc_id.value_as_string,
            availability_zones=["us-east-2a", "us-east-2b", "us-east-2c"]
        )

        self.subnet_id = CfnParameter(
            self, "SubnetId", type="String", description="The Subnet to be used for the Slurmdbd stack."
        )
        self.subnet = ec2.Subnet.from_subnet_id(self, "subnet", subnet_id=self.subnet_id.value_as_string)

        # define Target Group
        self._external_slurmdbd_target_group = self._add_external_slurmdbd_target_group()

        # define Network Load Balancer (NLB)
        self._external_slurmdbd_nlb = self._add_external_slurmdbd_load_balancer(
            target_group=self._external_slurmdbd_target_group
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

        # use cfn-init and cfn-hup configure instance
        self._cfn_init_config = self._add_cfn_init_config()

        # create management security group with SSH access from anywhere (TEMPORARY!)
        self._ssh_server_sg, self._ssh_client_sg = self._add_management_security_groups()

        # create a pair of security groups for the slurm accounting traffic across
        # between cluster head node and external slurmdbd instance via port 6819
        self._slurmdbd_server_sg, self._slurmdbd_client_sg = self._add_slurmdbd_accounting_security_groups()

        # create Launch Template
        self._launch_template = self._add_external_slurmdbd_launch_template()

        # define EC2 Auto Scaling Group (ASG)
        self._external_slurmdbd_asg = self._add_external_slurmdbd_auto_scaling_group()

        # Create a CloudWatch log group
        self._log_group = self._add_cloudwatch_log_group()

        # define IAM role and necessary IAM policies
        self._role = self._add_iam_role()

    def _add_cfn_init_config(self):
        dna_json_content = {
            "dbms_uri": self.dbms_uri.value_as_string,
            "dbms_username": self.dbms_username.value_as_string,
            "dbms_database_name": self.dbms_database_name.value_as_string,
            "dbms_password_secret_arn": self.dbms_password_secret_arn.value_as_string,
            "munge_key_secret_arn": self.munge_key_secret_arn.value_as_string,
            "region": self.region,
            "stack_name": self.stack_name,
            "nlb_dns_name": self._external_slurmdbd_nlb.load_balancer_dns_name,
            "is_external_slurmdbd": True,
        }

        return {
            "configSets": {"default": ["setup", "configure"]},
            "setup": {
                "files": {
                    "/etc/chef/dna.json": {
                        "content": Fn.sub(json.dumps(dna_json_content)),
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                    },
                },
                "chef": {
                    "command": (
                        "cinc-client --local-mode --config /etc/chef/client.rb --log_level info "
                        "--logfile /var/log/chef-client.log --force-formatter --no-color "
                        "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json "
                        "--override-runlist aws-parallelcluster-entrypoints::external_slurmdbd_config"
                    ),
                    "cwd": "/etc/chef",
                },
            },
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

    def _add_external_slurmdbd_target_group(self):
        return elbv2.NetworkTargetGroup(
            self,
            # TODO: add resource name!
            "External-Slurmdbd-TG",
            health_check=elbv2.HealthCheck(
                port="6819",
                protocol=elbv2.Protocol.TCP,
            ),
            port=6819,
            protocol=elbv2.Protocol.TCP,
            target_type=elbv2.TargetType.INSTANCE,
            vpc=self.vpc,
        )

    def _add_management_security_groups(self):
        server_sg = ec2.SecurityGroup(
            self,
            "SSHServerSecurityGroup",
            description="Allow SSH access to slurmdbd instance (server)",
            vpc=self.vpc,
        )
        client_sg = ec2.SecurityGroup(
            self,
            "SSHClientSecurityGroup",
            description="Allow SSH access to slurmdbd instance (client)",
            vpc=self.vpc,
        )
        server_sg.add_ingress_rule(
            peer=client_sg, connection=ec2.Port.tcp(22), description="Allow SSH access from client SG"
        )
        client_sg.add_egress_rule(
            peer=server_sg, connection=ec2.Port.tcp(22), description="Allow SSH access to server SG"
        )
        return server_sg, client_sg

    def _add_slurmdbd_accounting_security_groups(self):
        slurmdbd_server_sg = ec2.SecurityGroup(
            self,
            "SlurmdbdServerSecurityGroup",
            description="Allow Slurm accounting traffic to the slurmdbd instance (server)",
            vpc=self.vpc,
        )

        slurmdbd_client_sg = ec2.SecurityGroup(
            self,
            "SlurmdbdClientSecurityGroup",
            description="Allow Slurm accounting traffic from the cluster head node (client)",
            vpc=self.vpc,
        )

        slurmdbd_server_sg.add_ingress_rule(
            peer=slurmdbd_client_sg,
            connection=ec2.Port.tcp(6819),
            description="Allow Slurm accounting traffic from the cluster head node",
        )

        slurmdbd_client_sg.add_egress_rule(
            peer=slurmdbd_server_sg,
            connection=ec2.Port.tcp(6819),
            description="Allow Slurm accounting traffic to the slurmdbd instance",
        )

        return slurmdbd_server_sg, slurmdbd_client_sg

    def _add_external_slurmdbd_launch_template(self):
        # Define a CfnParameter for the AMI ID
        # This AMI should be Parallel Cluster AMI, which has installed Slurm and related software
        ami_id_param = CfnParameter(self, "AmiId", type="String", description="The AMI id for the EC2 instance.")
        instance_type_param = CfnParameter(
            self,
            "InstanceType",
            type="String",
            description="The instance type for the EC2 instance",
        )
        key_name_param = CfnParameter(
            self,
            "KeyName",
            type="String",
            description="The SSH key name to access the instance (for management purposes only)",
        )

        launch_template_data = ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
            key_name=key_name_param.value_as_string,
            image_id=ami_id_param.value_as_string,
            instance_type=instance_type_param.value_as_string,
            security_group_ids=[
                self._ssh_server_sg.security_group_id,
                self._slurmdbd_server_sg.security_group_id,
            ],
            user_data=Fn.base64(
                Fn.sub(
                    get_user_data_content("../resources/user_data.sh"),
                    {
                        **{
                            "custom_cookbook_url": self.custom_cookbook_url_param.value_as_string,
                        },
                    },
                )
            ),
        )

        launch_template = ec2.CfnLaunchTemplate(self, "LaunchTemplate", launch_template_data=launch_template_data)
        launch_template.add_metadata("AWS::CloudFormation::Init", self._cfn_init_config)

        return launch_template

    def _add_external_slurmdbd_load_balancer(
        self,
        target_group,
    ):
        nlb = elbv2.NetworkLoadBalancer(
            self,
            "External-Slurmdbd-NLB",
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=[self.subnet]),
            internet_facing=False,
        )

        # add listener to NLB
        listener = nlb.add_listener("External-Slurmdbd-Listener", port=6819)
        listener.add_target_groups("External-Slurmdbd-Target", target_group)

        return nlb

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
        role = iam.Role(
            self,
            "SlurmdbdInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="Role for Slurmdbd EC2 instance to access necessary AWS resources",
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    self.dbms_password_secret_arn.value_as_string,
                    self.munge_key_secret_arn.value_as_string,
                ],
                effect=iam.Effect.ALLOW,
                sid="SecretsManagerPolicy",
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[self._log_group.log_group_arn],
                effect=iam.Effect.ALLOW,
                sid="CloudWatchLogsPolicy",
            )
        )

        return role

    def _add_cloudwatch_log_group(self):
        # Create a new CloudWatch log group
        return logs.LogGroup(
            self,
            "SlurmdbdLogGroup",
            log_group_name=f"/aws/slurmdbd/{self.stack_name}",
            retention=logs.RetentionDays.ONE_WEEK,
        )
