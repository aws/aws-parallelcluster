from typing import List

from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subscriptions
from aws_cdk import core
from aws_cdk.core import Construct, Fn, Stack

from pcluster.config.cluster_config import BaseClusterConfig
from pcluster.constants import IAM_ROLE_PATH
from pcluster.models.s3_bucket import S3Bucket
from pcluster.templates.cdk_builder_utils import (
    PCLUSTER_LAMBDA_PREFIX,
    get_cloud_watch_logs_policy_statement,
    get_cloud_watch_logs_retention_days,
    get_lambda_log_group_prefix,
)
from pcluster.utils import random_alphanumeric


class CostBudgets:
    """Create the budgets based on the configuration file."""

    def __init__(
        self,
        scope: Construct,
        cluster_config: BaseClusterConfig,
        is_batch: bool,
        create_lambda_role: bool,
        bucket: S3Bucket,
    ):
        self.cluster_config = cluster_config
        self.scope = scope
        self.is_batch = is_batch
        self.create_lambda_role = create_lambda_role
        self.sns_arn = None
        self.bucket = bucket
        self._create_budgets()

    def _create_budgets(self):
        """Create the Cfn templates for the list of budgets."""
        budget_list = self.cluster_config.dev_settings.budgets
        self.cfn_budget_list = []

        for index, budget in enumerate(budget_list):
            cfn_budget = self._add_parameters(budget, index)
            self.cfn_budget_list.append(cfn_budget)

    def _add_parameters(self, budget, index):
        """Add each budget's parameters."""
        if budget.budget_category == "queue":
            name = f"{self.cluster_config.cluster_name}-{index}-{budget.queue_name}-{self.cluster_config.region}"
        elif budget.budget_category == "cluster":
            name = f"{self.cluster_config.cluster_name}-{index}-{self.cluster_config.region}"
        else:
            name = f"{self.cluster_config.cluster_name}-{index}-custom-{self.cluster_config.region}"

        budget_data = budgets.CfnBudget.BudgetDataProperty(
            # Some fields need replacement to be updated in Cfn. The name without a hash would create duplicates.
            # The chance of collision (assuming reasonably uniform distribution) is < 0.000002% with 5 alphanum digits
            budget_name=name + random_alphanumeric(5),
            budget_type="COST",
            time_unit=budget.time_unit,
            budget_limit=budgets.CfnBudget.SpendProperty(
                amount=budget.budget_limit.amount, unit=budget.budget_limit.unit
            ),
            cost_filters=(
                budget.cost_filters
                if budget.budget_category == "custom"
                else (
                    {"TagKeyValue": [f"user:parallelcluster:cluster-name${self.cluster_config.cluster_name}"]}
                    if budget.budget_category == "cluster"
                    else (
                        {
                            "TagKeyValue": [
                                f"user:parallelcluster:queue-name${budget.queue_name}",
                                f"user:parallelcluster:cluster-name${self.cluster_config.cluster_name}",
                            ]
                        }
                    )
                )
            ),
        )
        notifications_with_subscribers = (
            self._add_budget_notifications(budget) if budget.notifications_with_subscribers else None
        )
        budget_id = f"Budget{str(index)}"
        cfn_budget = budgets.CfnBudget(
            self.scope, budget_id, budget=budget_data, notifications_with_subscribers=notifications_with_subscribers
        )
        return cfn_budget

    def _add_budget_notifications(self, budget):
        """Create the notifications with subscribers for each budget."""
        notifications_with_subscribers = []
        for single_notification in budget.notifications_with_subscribers:
            subscribers = [
                budgets.CfnBudget.SubscriberProperty(
                    address=subscriber.address,
                    subscription_type=subscriber.subscription_type,
                )
                for subscriber in single_notification.subscribers
            ]

            if single_notification.trigger_fleet_stop:
                if not self.sns_arn:
                    self._create_lambda_and_sns()
                subscribers.append(
                    budgets.CfnBudget.SubscriberProperty(
                        address=self.sns_arn,
                        subscription_type="SNS",
                    )
                )
            notifications_with_subscribers.append(
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator=single_notification.notification.comparison_operator,
                        notification_type=single_notification.notification.notification_type,
                        threshold_type=single_notification.notification.threshold_type,
                        threshold=single_notification.notification.threshold,
                    ),
                    subscribers=subscribers,
                )
            )
        return notifications_with_subscribers

    def _create_lambda_and_sns(self):
        """Create an sns topic and a lambda function to stop compute fleet when triggered."""
        topic_name = f"pcluster-BudgetTopic-{self.cluster_config.cluster_name}"
        self.sns_topic = sns.Topic(
            self.scope,
            topic_name,
            display_name=topic_name,
            fifo=False,
            topic_name=topic_name,
        )
        self.sns_arn = self.sns_topic.topic_arn
        self.sns_topic.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["SNS:Publish"],
                effect=iam.Effect.ALLOW,
                resources=[self.sns_arn],
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
            )
        )

        lambda_env = {
            "TABLE_NAME": self.scope.dynamodb_table_status.ref if not self.is_batch else "NONE",
            "IS_BATCH": "TRUE" if self.is_batch else "FALSE",
            "CE_NAME": self.scope.scheduler_resources.compute_env.ref if self.is_batch else "NONE",
        }

        function_id = "FleetStop"
        function_name = f"{PCLUSTER_LAMBDA_PREFIX}{function_id}-{self._stack_unique_id()}"

        budget_triggered_lambda_role = None

        if self.create_lambda_role:
            slurm_policy = iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
                effect=iam.Effect.ALLOW,
                resources=[
                    self.scope.format_arn(
                        service="dynamodb",
                        resource="table/parallelcluster-*",
                        region=self.scope.region,
                        account=self.scope.account,
                    ),
                ],
                sid="DynamoDbStopFleetPolicy",
            )
            batch_policy = iam.PolicyStatement(
                actions=["batch:UpdateComputeEnvironment"],
                effect=iam.Effect.ALLOW,
                resources=["*"],
                sid="BatchStopComputeEnv",
            )

            budget_triggered_lambda_role = add_lambda_role(
                scope=self.scope,
                function_id=function_id,
                statements=[
                    (batch_policy if self.is_batch else slurm_policy),
                    get_cloud_watch_logs_policy_statement(
                        resource=self.scope.format_arn(
                            service="logs",
                            account=self.scope.account,
                            region=self.scope.region,
                            resource=get_lambda_log_group_prefix("FleetStop-*"),
                        )
                    ),
                ],
            )

        budget_triggered_lambda = awslambda.Function(
            self.scope,
            f"{function_id}Function",
            role=(
                budget_triggered_lambda_role
                if self.create_lambda_role
                else iam.Role.from_role_arn(
                    self.scope,
                    "LambdaFunctionsRole",
                    self.cluster_config.iam.roles.lambda_functions_role,
                )
            ),
            runtime=awslambda.Runtime.PYTHON_3_8,
            function_name=function_name,
            code=awslambda.Code.from_bucket(
                bucket=s3.Bucket.from_bucket_name(self.scope, "LambdaCodeBucket", self.bucket.name),
                key=f"{self.bucket.artifact_directory}/custom_resources/artifacts.zip",
            ),
            handler="budget_triggered_stop.handler",
            timeout=core.Duration.seconds(600),
            environment=lambda_env,
        )

        self.log_group = logs.CfnLogGroup(
            self.scope,
            f"{function_id}FunctionLogGroup",
            log_group_name=f"/aws/lambda/{function_name}",
            retention_in_days=get_cloud_watch_logs_retention_days(self.cluster_config),
        )

        self.sns_topic.add_subscription(sns_subscriptions.LambdaSubscription(budget_triggered_lambda))

    def _stack_unique_id(self):
        return Fn.select(2, Fn.split("/", Stack.of(self.scope).stack_id))


def add_lambda_role(scope, function_id: str, statements: List[iam.PolicyStatement]):
    """Return a CfnRole to be used for a Lambda function."""
    return iam.Role(
        scope,
        f"{function_id}FunctionExecutionRole",
        path=IAM_ROLE_PATH,
        assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        inline_policies={"LambdaPolicy": iam.PolicyDocument(statements=statements)},
    )
