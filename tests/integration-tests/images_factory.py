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
from utils import run_command, kebab_case


class Image:
    """Contain all static and dynamic data related to an image instance."""

    def __init__(self, image_id, config_file, region):
        self.image_id = image_id
        self.config_file = config_file
        self.region = region
        with open(config_file) as conf_file:
            self.config = yaml.safe_load(conf_file)
        self.image_tags = None
        self.creation_time = None
        self.build_log = None
        self.version = None
        self.image_status = None
        self.configuration_errors = None

    def build(self, raise_on_error=True, log_error=True):
        """Build image."""
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
        result = run_command(command, raise_on_error=raise_on_error, log_error=log_error)
        response = json.loads(result.stdout)
        try:
            if response["image"]["imageBuildStatus"] == "BUILD_IN_PROGRESS":
                self._update_image_info(response["image"])
            else:
                logging.error("Error building image: %s", response)
        except KeyError:
            if log_error:
                logging.error("Error building image: %s", result.stdout)

        if "configurationValidationErrors" in response:
            self.configuration_errors = response["configurationValidationErrors"]

        return response["image"] if "image" in response else response

    def delete(self, force=False):
        """Delete image."""
        command = ["pcluster", "delete-image", "--image-id", self.image_id, "--region", self.region]
        if force:
            command.extend(["--force", "true"])
        result = run_command(command).stdout
        response = json.loads(result.stdout)
        return response

    def describe(self):
        """Describe image."""
        logging.info("Describe image %s in region %s.", self.image_id, self.region)
        command = ["pcluster", "describe-image", "--image-id", self.image_id, "--region", self.region]
        result = run_command(command).stdout
        response = json.loads(result)
        self._update_image_info(response)
        return response

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
        result = run_command(command).stdout
        response = json.loads(result)
        return response

    def get_stack_events(self, **args):
        """Get image build stack events."""
        logging.info("Get image %s build log.", self.image_id)
        command = [
            "pcluster",
            "get-image-stack-events",
            "--region",
            self.region,
            "--image-id",
            self.image_id,
        ]
        for k, val in args.items():
            command.extend([f"--{kebab_case(k)}", str(val)])
        result = run_command(command).stdout
        response = json.loads(result)
        return response

    def list_log_streams(self):
        """Get image build log streams."""
        logging.info("Get image %s build log streams.", self.image_id)
        command = [
            "pcluster",
            "list-image-log-streams",
            "--region",
            self.region,
            "--image-id",
            self.image_id,
        ]
        result = run_command(command).stdout
        response = json.loads(result)
        return response

    def _update_image_info(self, image_info):
        ec2_ami_info = image_info.get("ec2AmiInfo")
        if ec2_ami_info:
            self.image_tags = ec2_ami_info.get("tags")
        self.creation_time = image_info.get("creationTime")
        self.build_log = image_info.get("buildLog")
        self.version = image_info.get("version")
        self.image_status = image_info.get("imageBuildStatus")


class ImagesFactory:
    """Manage creation and destruction of pcluster images."""

    def __init__(self):
        self.__created_images = {}

    def create_image(self, image: Image, raise_on_error=True, log_error=True):
        """
        Create a image with a given config.
        :param image: image to create.
        :param raise_on_error: raise exception if image creation fails
        :param log_error: log error when error occurs. This can be set to False when error is expected
        """
        logging.info("Build image %s with config %s", image.image_id, image.config_file)
        result = image.build(raise_on_error=raise_on_error, log_error=log_error)
        if "BUILD_IN_PROGRESS" in result:
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
