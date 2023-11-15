from aws_cdk import App, CfnParameter, Fn, Stack
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from constructs import Construct


class ExternalSlurmdbdStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # define networking stuff
        self.vpc_id = CfnParameter(self, "VPC_id", type="String", description="The VPC to be used for the Slurmdbd stack.")
        self.vpc = ec2.Vpc.from_lookup(self, "VPC", vpc_id=self.vpc_id.value_as_string)

        self.subnet_id = CfnParameter(self, "SubnetId", type="String", description="The Subnet to be used for the Slurmdbd stack.")
        self.subnet = ec2.Subnet.from_subnet_id(self, "subnet", subnet_id=self.subnet_id.value_as_string)

        # define Target Group
        self._external_slurmdbd_target_group = self._add_external_slurmdbd_target_group()

        # define Network Load Balancer (NLB)
        self._external_slurmdbd_nlb = self._add_external_slurmdbd_load_balancer(target_group=self._external_slurmdbd_target_group)

        # use cfn-init and cfn-hup configure instance
        self._cfn_init_config = self._add_cfn_init_config()

        # create management security group with SSH access from anywhere (TEMPORARY!)
        self._ssh_server_sg, self._ssh_client_sg = self._add_management_security_groups()

        # create Launch Template
        self._launch_template = self._add_external_slurmdbd_launch_template()

        # define EC2 Auto Scaling Group (ASG)
        self._external_slurmdbd_asg = self._add_external_slurmdbd_auto_scaling_group()

    def _add_cfn_init_config(self):
        return {
            "configSets": {"default": ["setup", "configure"]},
            "setup": {
                # TODO: * configuration of slurmdbd (same as done in config_slurm_accounting.rb), including:
                #           * configuration of munge systemd service;
                #           * retrieval of the munge key from Secret Manager (this requires an appropriate IAM policy);
                #           * configuration of slurmdbd systemd service;
                #           * retrieval of DBMS credentials from Secret Manager (this requires an appropriate IAM policy);
                #           * creation of slurmdbd.conf;
                #           * start of slurmdbd;
                #           * minimal bootstrapping of Slurm Accounting database.
                #        * configuration of CloudWatch log group creation and slurmdbd log push to the CW log group (this require appropriate IAM policies).
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
                            "[main]\n"
                            "stack=${StackId}\n"
                            "region=${Region}\n"
                            "interval=2\n",
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
            peer=client_sg,
            connection=ec2.Port.tcp(22),
            description="Allow SSH access from client SG"
        )
        client_sg.add_egress_rule(
            peer=server_sg,
            connection=ec2.Port.tcp(22),
            description="Allow SSH access to server SG"
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
            description="The instance type for the EC2 instance"
        )
        key_name_param = CfnParameter(
            self,
            "KeyName",
            type="String",
            description="The SSH key name to access the instance (for management purposes only)"
        )

        launch_template_data = ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
            key_name=key_name_param.value_as_string,
            image_id=ami_id_param.value_as_string,
            instance_type=instance_type_param.value_as_string,
            security_group_ids=[self._ssh_server_sg.security_group_id]
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
            internet_facing=False)

        # add listener to NLB
        listener = nlb.add_listener("External-Slurmdbd-Listener", port=6819)
        listener.add_target_groups("External-Slurmdbd-Target", target_group)

        return nlb

    def _add_external_slurmdbd_auto_scaling_group(self):
        return autoscaling.CfnAutoScalingGroup(
            self,
            "External-Slurmdbd-ASG",
            max_size="1",
            min_size="1",
            desired_capacity="1",
            launch_template=autoscaling.CfnAutoScalingGroup.LaunchTemplateSpecificationProperty(
                version=self._launch_template.attr_latest_version_number, launch_template_id=self._launch_template.ref
            ),
            vpc_zone_identifier=[self.subnet_id.value_as_string],
        )
