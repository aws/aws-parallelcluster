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
from collections import defaultdict, namedtuple

from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_logs as logs
from aws_cdk.core import Construct, Duration, Stack

from pcluster.config.cluster_config import (
    BaseClusterConfig,
    CommonSchedulerClusterConfig,
    SharedFsxLustre,
    SharedStorageType,
)

MAX_WIDTH = 24


class Coord:
    """Create coordinates for locating cloudwatch graphs."""

    def __init__(self, x_value: int, y_value: int):
        self.x_value = x_value
        self.y_value = y_value


_PclusterMetric = namedtuple(
    "_PclusterMetric", ["title", "metrics", "supported_vol_types", "namespace", "additional_dimensions"]
)
_CustomMetricFilter = namedtuple("MetricFilter", ["metric_name", "filter_pattern"])
_Filter = namedtuple("new_filter", ["pattern", "param"])
_CWLogWidget = namedtuple(
    "_CWLogWidget",
    ["title", "conditions", "fields", "filters", "sort", "limit"],
)


def new_pcluster_metric(title=None, metrics=None, supported_vol_types=None, namespace=None, additional_dimensions=None):
    return _PclusterMetric(title, metrics, supported_vol_types, namespace, additional_dimensions)


class CWDashboardConstruct(Construct):
    """Create the resources required when creating cloudwatch dashboard."""

    def __init__(
        self,
        scope: Construct,
        stack_name: str,
        id: str,
        cluster_config: BaseClusterConfig,
        head_node_instance: ec2.CfnInstance,
        shared_storage_infos: dict,
        cw_log_group_name: str,
        cw_log_group: logs.CfnLogGroup,
    ):
        super().__init__(scope, id)
        self.stack_scope = scope
        self.stack_name = stack_name
        self.config = cluster_config
        self.head_node_instance = head_node_instance
        self.shared_storage_infos = shared_storage_infos
        self.cw_log_group_name = cw_log_group_name
        self.cw_log_group = cw_log_group

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
            if len(self.shared_storage_infos[storage_type]) > 0:
                self._add_volume_metrics_graphs(title, storage_type, ebs_metrics, conditional_ebs_metrics)

        # Add EFS metrics graphs
        if len(self.shared_storage_infos[SharedStorageType.EFS]) > 0:
            self._add_efs_metrics_graphs()

        # Add FSx metrics graphs
        if len(self.shared_storage_infos[SharedStorageType.FSX]) > 0:
            self._add_fsx_metrics_graphs()

        # Head Node logs add custom metrics if cw_log and metrics are enabled
        if self.config.is_cw_logging_enabled:
            self._add_cw_log()
            self.add_custom_error_metrics()

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
                        return
            else:
                self.empty_section = False
                return

    def _add_text_widget(self, markdown):
        """Add the textwidget to the cloudwatch dashboard and update coordinates."""
        text_widget = cloudwatch.TextWidget(markdown="\n" + markdown + "\n", height=1, width=MAX_WIDTH)
        text_widget.position(x=self.coord.x_value, y=self.coord.y_value)
        self.cloudwatch_dashboard.add_widgets(text_widget)
        self._update_coord_after_section(d_y=1)

    def _generate_graph_widget(self, title, metric_list, error_label):
        """Generate a graph widget and update the coordinates."""
        if error_label:
            widget = cloudwatch.GraphWidget(
                title=title,
                left=metric_list,
                region=self._stack_region,
                width=self.graph_width,
                height=self.graph_height,
                left_annotations=[
                    cloudwatch.HorizontalAnnotation(
                        value=1, label="github.com/aws/aws-parallelcluster/wiki#known-issues-"
                    ),
                ],
            )
        else:
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

    def _generate_metrics_list(self, metrics_param):
        metric_list = []
        dimensions_map = {"InstanceId": self.head_node_instance.ref}
        dimensions_map.update(metrics_param.additional_dimensions if metrics_param.additional_dimensions else {})
        for metric in metrics_param.metrics:
            cloudwatch_metric = cloudwatch.Metric(
                namespace=metrics_param.namespace, metric_name=metric, dimensions_map=dimensions_map
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
                graph_widget = self._generate_graph_widget(metric_condition_params.title, metric_list, False)
                widgets_list.append(graph_widget)
        return widgets_list

    def custom_pcluster_metric_filter(self, metric_name, filter_pattern, custom_namespace):
        """Adding custom metric filter from named tuple."""
        metric_filter = logs.CfnMetricFilter(
            scope=self.stack_scope,
            id=metric_name + " Filter",
            filter_pattern=filter_pattern,
            log_group_name=self.cw_log_group_name,
            metric_transformations=[
                logs.CfnMetricFilter.MetricTransformationProperty(
                    metric_namespace=custom_namespace,
                    metric_name=metric_name,
                    metric_value="1",
                    default_value=0,
                )
            ],
        )
        metric_filter.add_depends_on(self.cw_log_group)
        return metric_filter

    def add_custom_error_metrics(self):
        """Create custom error metric filter and outputs to cloudwatch graph."""
        jobs_not_starting_errors = [
            _CustomMetricFilter(
                metric_name="Mismatch between IAM Group",
                filter_pattern="?UnauthorizedOperation ?AccessDeniedException",
            ),
            _CustomMetricFilter(
                metric_name="AMI larger than root volume",
                filter_pattern="InvalidBlockDeviceMapping",
            ),
            _CustomMetricFilter(
                metric_name="Vcpu limit",
                filter_pattern="VcpuLimitExceeded",
            ),
            _CustomMetricFilter(
                metric_name="Volume Limit",
                filter_pattern="?VolumeLimitExceeded ?InsufficientVolumeCapacity",
            ),
            _CustomMetricFilter(
                metric_name="Node Capacity Insufficient",
                filter_pattern="?InsufficientInstanceCapacity ?InsufficientHostCapacity "
                "?InsufficientReservedInstanceCapacity ?InsufficientCapacity",
            ),
        ]

        custom_script_errors = [
            _CustomMetricFilter(
                metric_name="Cannot retrieve custom script",
                filter_pattern="error occurred 403 when calling the HeadObject operation Forbidden",
            ),
            _CustomMetricFilter(
                metric_name="Error With Custom Script",
                filter_pattern="Failed to run bootstrap recipes",
            ),
            _CustomMetricFilter(
                metric_name="Script Timeout",
                filter_pattern="WARNING Node bootstrap error Resume timeout "
                "expires state DOWN CLOUD POWERED DOWN NOT RESPONDING",
            ),
        ]

        compute_node_events = [
            _CustomMetricFilter(
                metric_name="Terminated EC2 compute node before job submission ",
                filter_pattern="WARNING Node state check no corresponding instance in EC2 for node",
            ),
            _CustomMetricFilter(
                metric_name="EC2 Health Check",
                filter_pattern="Nodes not responding setting DOWN",
            ),
            _CustomMetricFilter(
                metric_name="EC2 Maintenance Events",
                filter_pattern="Setting nodes failing health check type ec2_health_check to DRAIN",
            ),
            _CustomMetricFilter(
                metric_name="Slurm Health Check Failure",
                filter_pattern="Performing actions for health check type scheduled_events_check",
            ),
        ]

        other_potential_issues = [
            _CustomMetricFilter(
                metric_name="Errors and Warnings",
                filter_pattern="?error ?Error ?ERROR ?WARNING ?Warning ?warning",
            ),
        ]

        error_metric_dict = {
            "Other Error and Warning Messages": other_potential_issues,
            "Jobs Not Starting Errors": jobs_not_starting_errors,
            "Unexpected EC2 Termination": compute_node_events,
        }

        if self.config.head_node.custom_actions or (
            isinstance(self.config, CommonSchedulerClusterConfig) and self.config.do_compute_nodes_have_custom_actions
        ):
            error_metric_dict.update({"Custom Script Errors": custom_script_errors})

        self._add_text_widget("## Metrics for Common Errors")
        custom_namespace = "ParallelCluster/Errors/" + self.config.cluster_name
        widgets_list = []
        for title, metric_filters in error_metric_dict.items():
            metric_list = []
            for new_filter in metric_filters:
                self.custom_pcluster_metric_filter(
                    metric_name=new_filter.metric_name,
                    filter_pattern=new_filter.filter_pattern,
                    custom_namespace=custom_namespace,
                )
                cloudwatch_metric = cloudwatch.Metric(
                    namespace=custom_namespace,
                    metric_name=new_filter.metric_name,
                    period=Duration.minutes(1),
                    statistic="Sum",
                )
                metric_list.append(cloudwatch_metric)
            graph_widget = self._generate_graph_widget(title, metric_list, True)
            widgets_list.append(graph_widget)

        self.cloudwatch_dashboard.add_widgets(*widgets_list)
        self._update_coord_after_section(self.graph_height)

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
            graph_widget = self._generate_graph_widget(metrics_param.title, metric_list, False)
            widgets_list.append(graph_widget)
        return widgets_list

    def _add_fsx_widgets(self, storages_list):
        common_metrics = [
            new_pcluster_metric(title="Data Read/Write Ops", metrics=["DataReadOperations", "DataWriteOperations"]),
            new_pcluster_metric(title="Data Read/Write Bytes", metrics=["DataReadBytes", "DataWriteBytes"]),
        ]
        free_data_storage_capacity_graph_title = "Free Data Storage Capacity"
        lustre_metrics = common_metrics + [
            new_pcluster_metric(title=free_data_storage_capacity_graph_title, metrics=["FreeDataStorageCapacity"])
        ]
        namespace = "AWS/FSx"
        metric_graphs = defaultdict(list)
        for index, storage in enumerate(storages_list):
            if isinstance(storage.config, SharedFsxLustre):
                metrics = lustre_metrics
                dimensions_map = {"FileSystemId": storage.id}
            else:
                metrics = common_metrics
                dimensions_map = {"FileSystemId": storage.config.file_system_id, "VolumeId": storage.id}

                # FSx Ontap/OpenZFS do not provide free capacity metric. The code below generates the metric using math.
                free_capacity_metric = cloudwatch.MathExpression(
                    label=f"{storage.id} FreeDataStorageCapacity",
                    expression=f"capacity{index} - used_capacity{index}",
                    using_metrics={
                        f"capacity{index}": cloudwatch.Metric(
                            namespace=namespace,
                            metric_name="StorageCapacity",
                            dimensions_map=dimensions_map,
                        ),
                        f"used_capacity{index}": cloudwatch.Metric(
                            namespace=namespace,
                            metric_name="UsedStorageCapacity",
                            dimensions_map=dimensions_map,
                        ),
                    },
                )
                metric_graphs[free_data_storage_capacity_graph_title].append(free_capacity_metric)
            for metrics_param in metrics:
                metric_list = metric_graphs[metrics_param.title]
                for metric in metrics_param.metrics:
                    cloudwatch_metric = cloudwatch.Metric(
                        namespace=namespace,
                        metric_name=metric,
                        dimensions_map=dimensions_map,
                    )
                    metric_list.append(cloudwatch_metric)
        widgets_list = []
        for title, metric_list in metric_graphs.items():
            widgets_list.append(self._generate_graph_widget(title, metric_list, False))
        return widgets_list

    def _add_head_node_instance_metrics_graphs(self):
        # Create a text widget for subtitle "Head Node Instance Metrics"
        self._add_text_widget("## Head Node Instance Metrics")

        # EC2 metrics for graph for head node instance
        ec2_metrics = [
            new_pcluster_metric(title="CPU Utilization", metrics=["CPUUtilization"], namespace="AWS/EC2"),
            new_pcluster_metric(
                title="Network Packets In/Out", metrics=["NetworkPacketsIn", "NetworkPacketsOut"], namespace="AWS/EC2"
            ),
            new_pcluster_metric(title="Network In and Out", metrics=["NetworkIn", "NetworkOut"], namespace="AWS/EC2"),
            new_pcluster_metric(
                title="Disk Read/Write Bytes", metrics=["DiskReadBytes", "DiskWriteBytes"], namespace="AWS/EC2"
            ),
            new_pcluster_metric(
                title="Disk Read/Write Ops", metrics=["DiskReadOps", "DiskWriteOps"], namespace="AWS/EC2"
            ),
        ]

        # CW Agent metrics for graph for head node instance
        cwagent_metrics = [
            new_pcluster_metric(
                title="Disk Used Percent",
                metrics=["disk_used_percent"],
                namespace="CWAgent",
                additional_dimensions={"path": "/"},
            ),
            new_pcluster_metric(title="Memory Used Percent", metrics=["mem_used_percent"], namespace="CWAgent"),
        ]

        # Create graphs for EC2 metrics and CW Agent metrics and update coordinates
        widgets_list = []
        for metrics_param in ec2_metrics + cwagent_metrics:
            metrics_list = self._generate_metrics_list(metrics_param)
            graph_widget = self._generate_graph_widget(metrics_param.title, metrics_list, False)
            widgets_list.append(graph_widget)

        self.cloudwatch_dashboard.add_widgets(*widgets_list)
        self._update_coord_after_section(self.graph_height)

    def _add_volume_metrics_graphs(self, title, storage_type, ebs_metrics, conditional_ebs_metrics):
        self._add_text_widget(title)

        # Get a list of volumes
        volumes_list = self.shared_storage_infos[storage_type]

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
        efs_volumes_list = self.shared_storage_infos[SharedStorageType.EFS]

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
        fsx_volumes_list = self.shared_storage_infos[SharedStorageType.FSX]

        # Add FSx metrics graphs and update coordinates
        widgets_list = self._add_fsx_widgets(
            storages_list=fsx_volumes_list,
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
                        conditions=[Condition(["alinux2", "centos7", "rhel8"], base_os)],
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
