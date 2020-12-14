import json
import logging
import random
import string
import time

import boto3
import pkg_resources
from jinja2 import Environment, FileSystemLoader


class KMSKeyFactory:
    """Manage creation for kms key."""

    def __init__(self):
        self.iam_client = None
        self.kms_client = None
        self.kms_key_id = None
        self.account_id = None
        self.region = None
        self.partition = None
        self.iam_role = None
        self.iam_policy_arn_batch = None
        self.iam_policy_arn_traditional = None

    def create_kms_key(self, region):
        """
        Create a kms key with given region.
        :param region: Different region need to create different keys
        """
        self.region = region
        self.account_id = (
            boto3.client("sts", endpoint_url=_get_sts_endpoint(region), region_name=region)
            .get_caller_identity()
            .get("Account")
        )

        if self.kms_key_id:
            return self.kms_key_id

        self.iam_role = self._create_role(region)
        self.kms_key_id = self._create_kms_key(region)
        return self.kms_key_id

    def _create_role(self, region):
        """
        Create iam role in given region.
        :param region: Create different roles on different regions, since we need to attach different policies
        """
        random_string = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
        iam_role_name = "Integ_test_InstanceRole_{0}_{1}".format(self.region, random_string)

        iam_policy_name_batch = "".join("Integ_test_InstancePolicy_batch" + random_string)
        logging.info("iam policy for awsbatch is {0}".format(iam_policy_name_batch))
        iam_policy_name_traditional = "".join("Integ_test_InstancePolicy" + random_string)
        logging.info("iam_policy for traditional scheduler is {0}".format(iam_policy_name_traditional))

        self.iam_client = boto3.client("iam", region_name=region)

        # Create the iam role
        logging.info("creating iam role {0} for creating KMS key...".format(iam_role_name))

        self.partition = next(
            ("aws-" + partition for partition in ["us-gov", "cn"] if self.region.startswith(partition)), "aws"
        )
        domain_suffix = ".cn" if self.partition == "aws-cn" else ""

        # Add EC2 as trust entity of the IAM role
        trust_relationship_policy_ec2 = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com{0}".format(domain_suffix)},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        self.iam_client.create_role(
            RoleName=iam_role_name,
            AssumeRolePolicyDocument=json.dumps(trust_relationship_policy_ec2),
            Description="Role for create custom KMS key",
        )
        # Having time.sleep here because because it take a while for the the IAM role to become valid for use in the
        # put_key_policy step for creating KMS key, read the following link for reference :
        # https://stackoverflow.com/questions/20156043/how-long-should-i-wait-after-applying-an-aws-iam-policy-before-it-is-valid
        time.sleep(15)

        # create instance policies for awsbatch and traditional schedulers
        self.iam_policy_arn_batch = self._create_iam_policies(iam_policy_name_batch, "awsbatch")
        self.iam_policy_arn_traditional = self._create_iam_policies(iam_policy_name_traditional, "traditional")

        # attach the Instance policies to the role
        logging.info("Attaching iam policy to the role {0}...".format(iam_role_name))

        # attach the Instance policy for awsBatch
        self.iam_client.attach_role_policy(RoleName=iam_role_name, PolicyArn=self.iam_policy_arn_batch)

        # attach the Instance policy for traditional scheduler
        self.iam_client.attach_role_policy(RoleName=iam_role_name, PolicyArn=self.iam_policy_arn_traditional)

        logging.info("Iam role is ready: {0}".format(iam_role_name))
        return iam_role_name

    def _create_iam_policies(self, iam_policy_name, scheduler):
        # the param "scheduler" here can have the value "awsbatch" and "traditional"

        # create the iam policy
        # for different scheduler, attach different instance policy
        logging.info("Creating iam policy {0} for iam role...".format(iam_policy_name))
        file_loader = FileSystemLoader(pkg_resources.resource_filename(__name__, "/../../resources"))
        env = Environment(loader=file_loader, trim_blocks=True, lstrip_blocks=True)
        policy_filename = (
            "batch_instance_policy.json" if scheduler == "awsbatch" else "traditional_instance_policy.json"
        )
        parallel_cluster_instance_policy = env.get_template(policy_filename).render(
            partition=self.partition,
            region=self.region,
            account_id=self.account_id,
            cluster_bucket_name="parallelcluster-*",
        )

        policy_res = self.iam_client.create_policy(
            PolicyName=iam_policy_name, PolicyDocument=parallel_cluster_instance_policy
        )
        policy_arn = policy_res["Policy"]["Arn"]
        return policy_arn

    def _create_kms_key(self, region):
        # create KMS key
        self.kms_client = boto3.client("kms", region_name=region)
        random_string = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
        key_alias = "alias/Integ_test_KMS_{0}_{1}".format(self.region, random_string)

        # If the key already existed, use the existing key
        for alias in self.kms_client.list_aliases().get("Aliases"):
            if alias.get("AliasName") == key_alias:
                kms_key_id = alias.get("TargetKeyId")
                logging.info("Use existing KMS key {0}".format(kms_key_id))
                return kms_key_id

        # if the key doesn't existed in the account, create a new key
        logging.info("Creating KMS key...")
        response = self.kms_client.create_key(
            Description="create kms key",
            KeyUsage="ENCRYPT_DECRYPT",
            Origin="AWS_KMS",
            BypassPolicyLockoutSafetyCheck=False,
        )
        kms_key_id = response["KeyMetadata"]["KeyId"]

        # create KMS key policy
        logging.info("Attaching key policy...")
        file_loader = FileSystemLoader(pkg_resources.resource_filename(__name__, "/../../resources"))
        env = Environment(loader=file_loader, trim_blocks=True, lstrip_blocks=True)
        key_policy = env.get_template("key_policy.json").render(
            partition=self.partition, account_id=self.account_id, iam_role_name=self.iam_role
        )

        # attach key policy to the key
        logging.info("Kms key {0} is  ".format(kms_key_id))
        # poll_on_key_creation(kms_key_id, self.kms_client)
        self.kms_client.put_key_policy(
            KeyId=kms_key_id,
            Policy=key_policy,
            PolicyName="default",
        )

        # create alias for the key
        self.kms_client.create_alias(
            AliasName=key_alias,
            TargetKeyId=kms_key_id,
        )
        logging.info("Kms key {0} is  ready".format(kms_key_id))
        return kms_key_id

    def release_all(self):
        """Release all resources"""
        self._release_iam_policy()
        self._release_iam_role()
        self._release_kms_key()

    def _release_iam_policy(self):
        if self.iam_policy_arn_batch or self.iam_policy_arn_traditional:
            logging.info("Deleting iam policy for awsbatch %s" % self.iam_policy_arn_batch)
            # detach iam policy for awsbatch from iam role
            self.iam_client.detach_role_policy(RoleName=self.iam_role, PolicyArn=self.iam_policy_arn_batch)
            # delete the awsbatch policy
            self.iam_client.delete_policy(PolicyArn=self.iam_policy_arn_batch)
            logging.info("Deleting iam policy for traditional scheduler %s" % self.iam_policy_arn_traditional)
            # detach iam policy for traditional schedluer from iam role
            self.iam_client.detach_role_policy(RoleName=self.iam_role, PolicyArn=self.iam_policy_arn_traditional)
            # delete the traditional schedluer policy
            self.iam_client.delete_policy(PolicyArn=self.iam_policy_arn_traditional)

    def _release_iam_role(self):
        logging.info("Deleting iam role %s" % self.iam_role)
        self.iam_client.delete_role(
            RoleName=self.iam_role,
        )

    def _release_kms_key(self):
        logging.info("Scheduling delete Kms key %s" % self.iam_role)
        self.kms_client.schedule_key_deletion(
            KeyId=self.kms_key_id,
            # The waiting period, specified in number of days. After the waiting period ends, AWS KMS deletes the CMK.
            # The waiting period is at least 7 days.
            PendingWindowInDays=7,
        )


def _get_sts_endpoint(region):
    """Get regionalized STS endpoint."""
    return "https://sts.{0}.{1}".format(region, "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com")
