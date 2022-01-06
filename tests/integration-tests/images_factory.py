# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import json
import logging

import yaml
from framework.credential_providers import run_pcluster_command
from utils import kebab_case


class Image:
    """Contain all static and dynamic data related to an image instance."""

    def __init__(self, image_id, config_file, region):
        self.image_id = image_id
        self.config_file = config_file
        self.region = region
        with open(config_file, encoding="utf-8") as conf_file:
            self.config = yaml.safe_load(conf_file)
        self.image_tags = None
        self.creation_time = None
        self.build_log = None
        self.version = None
        self.image_status = None
        self.configuration_errors = None
        self.message = None
        self.ec2_image_id = None

    @staticmethod
    def list_images(**kwargs):
        """List images."""
        command = ["pcluster", "list-images"]
        for k, val in kwargs.items():
            command.extend([f"--{kebab_case(k)}", str(val)])
        result = run_pcluster_command(command)
        response = json.loads(result.stdout)
        return response

    def build(self, **kwargs):
        """Build image."""
        raise_on_error = kwargs.pop("raise_on_error", True)
        log_error = kwargs.pop("log_error", True)

        command = [
            "pcluster",
            "build-image",
            "--image-id",
            self.image_id,
            "--region",
            self.region,
            "--image-configuration",
            self.config_file,
        ]

        for k, val in kwargs.items():
            command.extend([f"--{kebab_case(k)}", str(val)])

        result = run_pcluster_command(command, raise_on_error=raise_on_error, log_error=log_error)
        response = json.loads(result.stdout)
        try:
            if response["image"]["imageBuildStatus"] == "BUILD_IN_PROGRESS":
                self._update_image_info(response["image"])
            elif log_error:
                logging.error("Error building image: %s", response)
        except KeyError:
            if log_error:
                logging.error("Error building image: %s", result.stdout)
            if raise_on_error:
                raise

        if "configurationValidationErrors" in response:
            self.configuration_errors = response["configurationValidationErrors"]

        if "message" in response:
            self.message = response["message"]

        return response["image"] if "image" in response else response

    def delete(self, force=False):
        """Delete image."""
        command = ["pcluster", "delete-image", "--image-id", self.image_id, "--region", self.region]
        if force:
            command.extend(["--force", "true"])
        result = run_pcluster_command(command)
        response = json.loads(result.stdout)
        if "message" in response and response["message"].startswith("No image or stack associated"):
            logging.error("Delete on non-existing image: %s", self.image_id)
        else:
            self._update_image_info(response)
        return response

    def describe(self, log_on_error=False):
        """Describe image."""
        logging.info("Describe image %s in region %s.", self.image_id, self.region)
        command = ["pcluster", "describe-image", "--image-id", self.image_id, "--region", self.region]
        result = run_pcluster_command(command).stdout
        response = json.loads(result)
        if "message" in response and response["message"].startswith("No image or stack associated"):
            if log_on_error:
                logging.error("Describe on non-existing image: %s", self.image_id)
        else:
            self._update_image_info(response)
        return response

    def export_logs(self, **args):
        """Export the logs from the image build process."""
        logging.info("Get image %s build log.", self.image_id)
        command = ["pcluster", "export-image-logs", "--region", self.region, "--image-id", self.image_id]
        for k, val in args.items():
            command.extend([f"--{kebab_case(k)}", str(val)])
        result = run_pcluster_command(command)
        return json.loads(result.stdout)

    def get_log_events(self, log_stream_name, **args):
        """Get image build log events."""
        logging.info("Get image %s build log.", self.image_id)
        command = [
            "pcluster",
            "get-image-log-events",
            "--image-id",
            self.image_id,
            "--region",
            self.region,
            "--log-stream-name",
            log_stream_name,
        ]
        for k, val in args.items():
            if val is not None:
                command.extend([f"--{kebab_case(k)}", str(val)])
        result = run_pcluster_command(command).stdout
        response = json.loads(result)
        return response

    def get_stack_events(self, **args):
        """Get image build stack events."""
        logging.info("Get image %s build log.", self.image_id)
        command = ["pcluster", "get-image-stack-events", "--region", self.region, "--image-id", self.image_id]
        for k, val in args.items():
            command.extend([f"--{kebab_case(k)}", str(val)])
        result = run_pcluster_command(command).stdout
        response = json.loads(result)
        return response

    def list_log_streams(self):
        """Get image build log streams."""
        logging.info("Get image %s build log streams.", self.image_id)
        command = ["pcluster", "list-image-log-streams", "--region", self.region, "--image-id", self.image_id]
        result = run_pcluster_command(command).stdout
        response = json.loads(result)
        return response

    def _update_image_info(self, image_info):
        ec2_ami_info = image_info.get("ec2AmiInfo")
        if ec2_ami_info:
            self.image_tags = ec2_ami_info.get("tags")
            self.ec2_image_id = ec2_ami_info.get("amiId")
        self.creation_time = image_info.get("creationTime")
        self.build_log = image_info.get("buildLog")
        self.version = image_info.get("version")
        self.image_status = image_info.get("imageBuildStatus")


class ImagesFactory:
    """Manage creation and destruction of pcluster images."""

    def __init__(self):
        self.__created_images = {}

    def create_image(self, image: Image, **kwargs):
        """
        Create an image with a given config.
        :param image: image to create.
        :param raise_on_error: raise exception if image creation fails
        :param log_error: log error when error occurs. This can be set to False when error is expected
        """
        logging.info("Build image %s with config %s", image.image_id, image.config_file)
        result = image.build(**kwargs)
        if image.image_status == "BUILD_IN_PROGRESS":
            self.__created_images[image.image_id] = image
        return result

    def destroy_image(self, image: Image):
        """Delete a created image."""
        logging.info("Delete image %s", image.image_id)

        if image.image_id in self.__created_images:
            result = image.delete(force=True)
            del self.__created_images[image.image_id]
            return result
        logging.debug("Tried to delete non-existant image: %s", image.image.id)
        return None

    def destroy_all_images(self):
        """Destroy all created images."""
        logging.debug("Destroying all images")
        for image_id in list(self.__created_images.keys()):
            try:
                self.destroy_image(self.__created_images[image_id])
            except Exception as e:
                logging.error("Failed when destroying image %s with exception %s.", image_id, e)
