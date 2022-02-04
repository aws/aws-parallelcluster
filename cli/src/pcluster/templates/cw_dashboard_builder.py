# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from collections import namedtuple

from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_ec2 as ec2
from aws_cdk.core import Construct, Stack

from pcluster.config.cluster_config import BaseClusterConfig, SharedStorageType

MAX_WIDTH = 24


class Coord:
    """Create coordinates for locating cloudwatch graphs."""

    def __init__(self, x_value: int, y_value: int):
        self.x_value = x_value
        self.y_value = y_value


_PclusterMetric = namedtuple("_PclusterMetric", ["title", "metrics", "supported_vol_types"])
_Filter = namedtuple("new_filter", ["pattern", "param"])
_CWLogWidget = namedtuple(
    "_CWLogWidget",
    ["title", "conditions", "fields", "filters", "sort", "limit"],
)


def new_pcluster_metric(title=None, metrics=None, supported_vol_types=None):
    return _PclusterMetric(title, metrics, supported_vol_types)


class CWDashboardConstruct(Construct):
    """Create the resources required when creating cloudwatch dashboard."""

    def __init__(
        self,
        scope: Construct,
        stack_name: str,
        id: str,
        cluster_config: BaseClusterConfig,
        head_node_instance: ec2.CfnInstance,
        shared_storage_mappings: dict,
        cw_log_group_name: str,
    ):
        super().__init__(scope, id)
        self.stack_scope = scope
        self.stack_name = stack_name
        self.config = cluster_config
        self.head_node_instance = head_node_instance
        self.shared_storage_mappings = shared_storage_mappings
        self.cw_log_group_name = cw_log_group_name

        self.dashboard_name = self.stack_name + "-" + self._stack_region
        self.coord = Coord(x_value=0, y_value=0)
        self.graph_width = 6
        self.graph_height = 6
        self.logs_width = MAX_WIDTH
        self.logs_height = 6
        self.empty_section = True
        self.dashboard = None

        self._add_resources()

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    @property
    def _stack_region(self):
        return Stack.of(self).region

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_resources(self):

        # Initialize a cloudwatch dashboard
        self.cloudwatch_dashboard = cloudwatch.Dashboard(
            self.stack_scope, "CloudwatchDashboard", dashboard_name=self.dashboard_name
        )

        # Create a text widget for title "Head Node EC2 metrics"
        self._add_text_widget("# Head Node EC2 Metrics")

        # Add head node instance graphs
        self._add_head_node_instance_metrics_graphs()

        ebs_metrics = [
            new_pcluster_metric(title="Read/Write Ops", metrics=["VolumeReadOps", "VolumeWriteOps"]),
            new_pcluster_metric(title="Read/Write Bytes", metrics=["VolumeReadBytes", "VolumeWriteBytes"]),
            new_pcluster_metric(title="Total Read/Write Time", metrics=["VolumeTotalReadTime", "VolumeTotalWriteTime"]),
            new_pcluster_metric(title="Queue Length", metrics=["VolumeQueueLength"]),
            new_pcluster_metric(title="Idle Time", metrics=["VolumeIdleTime"]),
        ]

        conditional_ebs_metrics = [
            new_pcluster_metric(
                title="Consumed Read/Write Ops",
                metrics="VolumeConsumedReadWriteOps",
                supported_vol_types=["io1", "io2", "gp3"],
            ),
            new_pcluster_metric(
                title="Throughput Percentage",
                metrics="VolumeThroughputPercentage",
                supported_vol_types=["io1", "io2", "gp3"],
            ),
            new_pcluster_metric(
                title="Burst Balance", metrics="BurstBalance", supported_vol_types=["gp2", "st1", "sc1"]
            ),
        ]

        # Add EBS and RAID metrics graphs
        for storage_type, title in [
            (SharedStorageType.EBS, "## EBS Metrics"),
            (SharedStorageType.RAID, "## RAID Metrics"),
        ]:
            if len(self.shared_storage_mappings[storage_type]) > 0:
                self._add_volume_metrics_graphs(title, storage_type, ebs_metrics, conditional_ebs_metrics)

        # Add EFS metrics graphs
        if len(self.shared_storage_mappings[SharedStorageType.EFS]) > 0:
            self._add_efs_metrics_graphs()

        # Add FSx metrics graphs
        if len(self.shared_storage_mappings[SharedStorageType.FSX]) > 0:
            self._add_fsx_metrics_graphs()

        # Head Node logs, if CW Logs are enabled
        if self.config.is_cw_logging_enabled:
            self._add_cw_log()

    def _update_coord(self, d_x, d_y):
        """Calculate coordinates for the new graph."""
        self.coord.x_value = self.coord.x_value + d_x
        x_value = self.coord.x_value + d_x
        if x_value > MAX_WIDTH:  # updates both x and y values
            self.coord.x_value = 0
            self.coord.y_value += d_y

    def _update_coord_after_section(self, d_y):
        """Calculate section header coordinates."""
        self.coord.y_value = self.coord.y_value + d_y

    def _reset_coord(self):
        self.coord = Coord(0, 0)

    def _is_logs_section_empty(self, section_widgets):
        """Check if a section will be empty."""
        self.empty_section = True
        for log_params in section_widgets.widgets:
            if log_params.conditions:
                for cond_dict in log_params.conditions:
                    if cond_dict.param in cond_dict.allowed_values:
                        self.empty_section = False

    def _add_text_widget(self, markdown):
        """Add the textwidget to the cloudwatch dashboard and update coordinates."""
        text_widget = cloudwatch.TextWidget(markdown="\n" + markdown + "\n", height=1, width=MAX_WIDTH)
        text_widget.position(x=self.coord.x_value, y=self.coord.y_value)
        self.cloudwatch_dashboard.add_widgets(text_widget)
        self._update_coord_after_section(d_y=1)

    def _generate_graph_widget(self, title, metric_list):
        """Generate a graph widget and update the coordinates."""
        widget = cloudwatch.GraphWidget(
            title=title,
            left=metric_list,
            region=self._stack_region,
            width=self.graph_width,
            height=self.graph_height,
        )
        widget.position(x=self.coord.x_value, y=self.coord.y_value)
        self._update_coord(self.graph_width, self.graph_height)
        return widget

    def _generate_ec2_metrics_list(self, metrics):
        metric_list = []
        for metric in metrics:
            cloudwatch_metric = cloudwatch.Metric(
                namespace="AWS/EC2", metric_name=metric, dimensions_map={"InstanceId": self.head_node_instance.ref}
            )
            metric_list.append(cloudwatch_metric)
        return metric_list

    def _add_conditional_storage_widgets(
        self,
        conditional_metrics,
        volumes_list,
        namespace,
        dimension_vol_name,
        vol_attribute_name,
    ):
        """Add widgets for conditional metrics for EBS, Raid and EFS."""
        widgets_list = []
        for metric_condition_params in conditional_metrics:
            metric_list = []
            for volume in volumes_list:
                if getattr(volume.config, vol_attribute_name) in metric_condition_params.supported_vol_types:
                    cloudwatch_metric = cloudwatch.Metric(
                        namespace=namespace,
                        metric_name=metric_condition_params.metrics,
                        dimensions_map={dimension_vol_name: volume.id},
                    )
                    metric_list.append(cloudwatch_metric)

            if len(metric_list) > 0:  # Add the metrics only if there exist support volumes for it
                graph_widget = self._generate_graph_widget(metric_condition_params.title, metric_list)
                widgets_list.append(graph_widget)
        return widgets_list

    def _add_storage_widgets(self, metrics, storages_list, namespace, dimension_name):
        widgets_list = []
        for metrics_param in metrics:
            metric_list = []
            for metric in metrics_param.metrics:
                for storage in storages_list:
                    cloudwatch_metric = cloudwatch.Metric(
                        namespace=namespace,
                        metric_name=metric,
                        dimensions_map={dimension_name: storage.id},
                    )
                    metric_list.append(cloudwatch_metric)
            graph_widget = self._generate_graph_widget(metrics_param.title, metric_list)
            widgets_list.append(graph_widget)
        return widgets_list

    def _add_head_node_instance_metrics_graphs(self):
        # Create a text widget for subtitle "Head Node Instance Metrics"
        self._add_text_widget("## Head Node Instance Metrics")

        # EC2 metrics graph for head node instance
        ec2_metrics = [
            new_pcluster_metric(title="CPU Utilization", metrics=["CPUUtilization"]),
            new_pcluster_metric(title="Network Packets In/Out", metrics=["NetworkPacketsIn", "NetworkPacketsOut"]),
            new_pcluster_metric(title="Network In and Out", metrics=["NetworkIn", "NetworkOut"]),
            new_pcluster_metric(title="Disk Read/Write Bytes", metrics=["DiskReadBytes", "DiskWriteBytes"]),
            new_pcluster_metric(title="Disk Read/Write Ops", metrics=["DiskReadOps", "DiskWriteOps"]),
        ]

        # Create EC2 metrics graphs and update coordinates
        widgets_list = []
        for metrics_param in ec2_metrics:
            metrics_list = self._generate_ec2_metrics_list(metrics_param.metrics)
            graph_widget = self._generate_graph_widget(metrics_param.title, metrics_list)
            widgets_list.append(graph_widget)
        self.cloudwatch_dashboard.add_widgets(*widgets_list)
        self._update_coord_after_section(self.graph_height)

    def _add_volume_metrics_graphs(self, title, storage_type, ebs_metrics, conditional_ebs_metrics):
        self._add_text_widget(title)

        # Get a list of volumes
        volumes_list = self.shared_storage_mappings[storage_type]

        # Unconditional EBS metrics
        widgets_list = self._add_storage_widgets(
            metrics=ebs_metrics, storages_list=volumes_list, namespace="AWS/EBS", dimension_name="VolumeId"
        )

        # Conditional EBS metrics
        widgets_list += self._add_conditional_storage_widgets(
            conditional_metrics=conditional_ebs_metrics,
            volumes_list=volumes_list,
            namespace="AWS/EBS",
            dimension_vol_name="VolumeId",
            vol_attribute_name="volume_type",
        )

        # Add unconditional metrics graphs and conditional volumes metrics graphs
        self.cloudwatch_dashboard.add_widgets(*widgets_list)
        self._update_coord_after_section(self.graph_height)

    def _add_efs_metrics_graphs(self):
        self._add_text_widget("## EFS Metrics")
        efs_volumes_list = self.shared_storage_mappings[SharedStorageType.EFS]

        # Unconditional EFS metrics
        efs_metrics = [
            new_pcluster_metric(title="Burst Credit Balance", metrics=["BurstCreditBalance"]),
            new_pcluster_metric(title="Client Connections", metrics=["ClientConnections"]),
            new_pcluster_metric(title="Total IO Bytes", metrics=["TotalIOBytes"]),
            new_pcluster_metric(title="Permitted Throughput", metrics=["PermittedThroughput"]),
            new_pcluster_metric(title="Data Read/Write IO Bytes", metrics=["DataReadIOBytes", "DataWriteIOBytes"]),
        ]
        widgets_list = self._add_storage_widgets(
            metrics=efs_metrics, storages_list=efs_volumes_list, namespace="AWS/EFS", dimension_name="FileSystemId"
        )

        # Conditional EFS metrics
        conditional_efs_metrics_params = [
            new_pcluster_metric(
                title="Percent IO Limit", metrics="PercentIOLimit", supported_vol_types=["generalPurpose"]
            ),
        ]
        widgets_list += self._add_conditional_storage_widgets(
            conditional_metrics=conditional_efs_metrics_params,
            volumes_list=efs_volumes_list,
            namespace="AWS/EFS",
            dimension_vol_name="FileSystemId",
            vol_attribute_name="performance_mode",
        )

        # Add unconditional metrics graphs and conditional EFS metrics graphs
        self.cloudwatch_dashboard.add_widgets(*widgets_list)
        self._update_coord_after_section(self.graph_height)

    def _add_fsx_metrics_graphs(self):
        self._add_text_widget("## FSx Metrics")
        fsx_volumes_list = self.shared_storage_mappings[SharedStorageType.FSX]

        # Unconditional FSX metrics
        fsx_metrics = [
            new_pcluster_metric(title="Data Read/Write Ops", metrics=["DataReadOperations", "DataWriteOperations"]),
            new_pcluster_metric(title="Data Read/Write Bytes", metrics=["DataReadBytes", "DataWriteBytes"]),
            new_pcluster_metric(title="Free Data Storage Capacity", metrics=["FreeDataStorageCapacity"]),
        ]

        # Add FSx metrics graphs and update coordinates
        widgets_list = self._add_storage_widgets(
            metrics=fsx_metrics,
            storages_list=fsx_volumes_list,
            namespace="AWS/FSx",
            dimension_name="FileSystemId",
        )
        self.cloudwatch_dashboard.add_widgets(*widgets_list)
        self._update_coord_after_section(self.graph_height)

    def _add_cw_log(self):
        # Create a text widget for subtitle "Head Node Logs"
        self._add_text_widget("## Head Node Logs")

        dcv_enabled = self.config.is_dcv_enabled
        scheduler = self.config.scheduling.scheduler
        base_os = self.config.image.os
        head_private_ip = self.head_node_instance.attr_private_ip

        Condition = namedtuple("Condition", ["allowed_values", "param"])
        SectionWidgets = namedtuple("SectionWidgets", ["section_title", "widgets"])

        sections_widgets = [
            SectionWidgets(
                "ParallelCluster's logs",
                [
                    self._new_cw_log_widget(
                        title="clustermgtd",
                        conditions=[Condition(["slurm"], scheduler)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*clustermgtd")],
                    ),
                    self._new_cw_log_widget(
                        title="slurm_resume",
                        conditions=[Condition(["slurm"], scheduler)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*slurm_resume")],
                    ),
                    self._new_cw_log_widget(
                        title="slurm_suspend",
                        conditions=[Condition(["slurm"], scheduler)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*slurm_suspend")],
                    ),
                ],
            ),
            SectionWidgets(
                "Scheduler's logs",
                [
                    self._new_cw_log_widget(
                        title="slurmctld",
                        conditions=[Condition(["slurm"], scheduler)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*slurmctld")],
                    ),
                ],
            ),
            SectionWidgets(
                "NICE DCV integration logs",
                [
                    self._new_cw_log_widget(
                        title="dcv-ext-authenticator",
                        conditions=[Condition([True], dcv_enabled)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*dcv-ext-authenticator")],
                    ),
                    self._new_cw_log_widget(
                        title="dcv-authenticator",
                        conditions=[Condition([True], dcv_enabled)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*dcv-authenticator")],
                    ),
                    self._new_cw_log_widget(
                        title="dcv-agent",
                        conditions=[Condition([True], dcv_enabled)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*dcv-agent")],
                    ),
                    self._new_cw_log_widget(
                        title="dcv-xsession",
                        conditions=[Condition([True], dcv_enabled)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*dcv-xsession")],
                    ),
                    self._new_cw_log_widget(
                        title="dcv-server",
                        conditions=[Condition([True], dcv_enabled)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*dcv-server")],
                    ),
                    self._new_cw_log_widget(
                        title="dcv-session-launcher",
                        conditions=[Condition([True], dcv_enabled)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*dcv-session-launcher")],
                    ),
                    self._new_cw_log_widget(
                        title="Xdcv",
                        conditions=[Condition([True], dcv_enabled)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*Xdcv")],
                    ),
                ],
            ),
            SectionWidgets(
                "System's logs",
                [
                    self._new_cw_log_widget(
                        title="system-messages",
                        conditions=[Condition(["alinux2", "centos7"], base_os)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*system-messages")],
                    ),
                    self._new_cw_log_widget(
                        title="syslog",
                        conditions=[Condition(["ubuntu1804", "ubuntu2004"], base_os)],
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*syslog")],
                    ),
                    self._new_cw_log_widget(
                        title="cfn-init",
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*cfn-init")],
                    ),
                    self._new_cw_log_widget(
                        title="chef-client",
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*chef-client")],
                    ),
                    self._new_cw_log_widget(
                        title="cloud-init",
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*cloud-init$")],
                    ),
                    self._new_cw_log_widget(
                        title="supervisord",
                        filters=[self._new_filter(pattern=f"{head_private_ip}.*supervisord")],
                    ),
                ],
            ),
        ]
        for section_widgets in sections_widgets:
            self._is_logs_section_empty(section_widgets)
            if not self.empty_section:
                self._add_text_widget(f"## {section_widgets.section_title}")
                for log_params in section_widgets.widgets:

                    # Check if the log need to added
                    passed_condition = True
                    if log_params.conditions:
                        for cond_dict in log_params.conditions:
                            passed_condition = cond_dict.param in cond_dict.allowed_values

                    # Add logs to dashboard
                    if passed_condition:
                        query_lines = ["fields {0}".format(",".join(log_params.fields))]
                        for filter in log_params.filters:
                            query_lines.append(f"filter {filter.param} like /{filter.pattern}/")
                        query_lines.extend([f"sort {log_params.sort}", f"limit {log_params.limit}"])

                        widget = cloudwatch.LogQueryWidget(
                            title=log_params.title,
                            region=self._stack_region,
                            width=self.logs_width,
                            height=self.logs_height,
                            log_group_names=[self.cw_log_group_name],
                            query_lines=query_lines,
                        )
                        widget.position(x=self.coord.x_value, y=self.coord.y_value)
                        self._update_coord(self.logs_width, self.logs_height)
                        self.cloudwatch_dashboard.add_widgets(widget)

    def _new_cw_log_widget(self, title=None, conditions=None, fields=None, filters=None, sort=None, limit=None):
        if fields is None:
            fields = ["@timestamp", "@message"]
        if sort is None:
            sort = "@timestamp desc"
        if limit is None:
            limit = 100
        return _CWLogWidget(title, conditions, fields, filters, sort, limit)

    def _new_filter(self, pattern=None, param=None):
        if param is None:
            param = "@logStream"
        return _Filter(pattern, param)
