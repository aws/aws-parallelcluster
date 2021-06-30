#!/usr/bin/env bash
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

cp client/resources/sigv4_auth.py client/src/pcluster_client
patch -u -N client/src/pcluster_client/api_client.py < client/resources/api_client.py.diff
patch -u -N client/src/requirements.txt < client/resources/client-requirements.txt.diff
