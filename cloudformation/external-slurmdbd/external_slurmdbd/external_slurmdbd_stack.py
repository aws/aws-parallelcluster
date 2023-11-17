import json

from aws_cdk import App, CfnParameter, Fn, Stack
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from constructs import Construct

from pcluster.constants import EXTERNAL_SLURMDBD_ASG_SIZE


class ExternalSlurmdbdStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.stack = Stack(scope=scope, id=construct_id, **kwargs)

        # define networking stuff
        self.vpc_id = CfnParameter(
            self, "VPC_id", type="String", description="The VPC to be used for the Slurmdbd stack."
        )

        self.subnet_id = CfnParameter(
            self, "SubnetId", type="String", description="The Subnet to be used for the Slurmdbd stack."
        )

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
        self.munge_key_secret_arn = CfnParameter(
            self, "MungeKeySecretArn", type="String", description="Secret ARN for Munge key."
        )

        # use cfn-init and cfn-hup configure instance
        self._cfn_init_config = self._add_cfn_init_config()

        # create management security group with SSH access from anywhere (TEMPORARY!)
        self._ssh_server_sg, self._ssh_client_sg = self._add_management_security_groups()

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
            "dbms_uri": self.dbms_uri_param.value_as_string,
            "dbms_username": self.dbms_username_param.value_as_string,
            "dbms_password_secret_arn": self.dbms_password_secret_arn_param.value_as_string,
            "munge_key_secret_arn": self.munge_key_secret_arn_param.value_as_string,
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
                            "action=/usr/bin/echo 'I was triggered by a change in AWS::CloudFormation::Init metadata!' > /tmp/cfn_init_metadata_update.log\n"
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
                                "StackId": self.stack.stack_id,
                                "Region": self.stack.region,
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
        client_sg.add_egress_rule(
            peer=server_sg, connection=ec2.Port.tcp(22), description="Allow SSH access to server SG"
        )
        return server_sg, client_sg

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
            security_group_ids=[self._ssh_server_sg.security_group_id],
        )

        launch_template = ec2.CfnLaunchTemplate(
            self,
            "LaunchTemplate",
            launch_template_data=launch_template_data,
        )

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
            log_group_name=f"/aws/slurmdbd/{self.stack.stack_name}",
            retention=logs.RetentionDays.ONE_WEEK,
        )
