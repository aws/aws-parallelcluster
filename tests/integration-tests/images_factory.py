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
from utils import run_command


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

    def build(self):
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
        result = run_command(command).stdout
        self._update_image_info(json.loads(result).get("image"))
        return result

    def delete(self, force=False):
        """Delete image."""
        command = ["pcluster", "delete-image", "--image-id", self.image_id, "--region", self.region]
        if force:
            command.extend(["--force", "true"])
        result = run_command(command).stdout
        return result

    def describe(self):
        """Describe image."""
        logging.info("Describe image %s in region %s.", self.image_id, self.region)
        command = ["pcluster", "describe-image", "--image-id", self.image_id, "--region", self.region]
        result = run_command(command).stdout
        self._update_image_info(json.loads(result))
        return result

    def get_log_events(self):
        """Get image build log events."""
        logging.info("Get image %s build log.", self.image_id)
        command = ["pcluster", "get-image-log-events", "-r", self.region, "--log-stream-name", "3.0.0/1", self.image_id]
        result = run_command(command).stdout
        return result

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

    def create_image(self, image: Image):
        """
        Create a image with a given config.
        :param image: image to create.
        """
        logging.info("Build image %s with config %s", image.image_id, image.config_file)
        result = image.build()
        self.__created_images[image.image_id] = image
        return result

    def destroy_image(self, image: Image):
        """Delete a created image."""
        logging.info("Delete image %s", image.image_id)

        if image.image_id in self.__created_images:
            result = image.delete(force=True)
            del self.__created_images[image.image_id]
            return result

    def destroy_all_images(self):
        """Destroy all created images."""
        logging.debug("Destroying all images")
        for image_id in list(self.__created_images.keys()):
            try:
                self.destroy_image(self.__created_images[image_id])
            except Exception as e:
                logging.error("Failed when destroying image %s with exception %s.", image_id, e)
