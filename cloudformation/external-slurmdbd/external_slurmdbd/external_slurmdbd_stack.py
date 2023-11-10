from aws_cdk import App, CfnParameter, Fn, Stack
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from constructs import Construct


class ExternalSlurmdbdStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # define EC2 VPC
        self.vpc = ec2.Vpc(self, "VPC")

        # define Target Group
        self._external_slurmdbd_target_group = self._add_external_slurmdbd_target_group()

        # define Network Load Balancer (NLB)
        self._external_slurmdbd_nlb = self._add_external_slurmdbd_load_balancer(self._external_slurmdbd_target_group)

        # use cfn-init and cfn-hup configure instance
        self._cfn_init_config = self._add_cfn_init_config()

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
                    }
                }
            },
        }

    def _add_external_slurmdbd_target_group(self):
        return elbv2.NetworkTargetGroup(
            self,
            "External-Slurmdbd-TG",
            health_check=elbv2.HealthCheck(
                port="22",
                protocol=elbv2.Protocol.TCP,
            ),
            port=22,
            protocol=elbv2.Protocol.TCP,
            target_type=elbv2.TargetType.INSTANCE,
            vpc=self.vpc,
        )

    def _add_external_slurmdbd_launch_template(self):
        # Define a CfnParameter for the AMI ID
        # This AMI should be Parallel Cluster AMI, which has installed Slurm and related software
        ami_id_param = CfnParameter(self, "AmiId", type="String", description="The AMI id for the EC2 instance.")

        launch_template_data = ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
            image_id=ami_id_param.value_as_string,
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
        nlb = elbv2.NetworkLoadBalancer(self, "External-Slurmdbd-NLB", vpc=self.vpc, internet_facing=False)

        # add listener to NLB
        listener = nlb.add_listener("External-Slurmdbd-Listener", port=22)
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
            vpc_zone_identifier=[subnet.subnet_id for subnet in self.vpc.public_subnets],
        )
