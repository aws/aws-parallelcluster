# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import time
from multiprocessing import Process

from assertpy import assert_that

from pcluster.templates.import_cdk import start


def concurrent_imports(iterations=20, delay=0.1):
    threads = []
    for _ in range(0, iterations):
        threads.append(start())
        time.sleep(delay)

    for t in threads:
        t.join()


def test_import():
    """
    This test ensures concurrent cdk library imports work.

    Concurrent cdk library import might occur during cluster creation and update.
    Here we test it doesn't break for some unknown race condition.
    """
    # We need to use a separate process to test concurrent imports
    # because cdk library might be already imported in the test process by previous tests
    p = Process(target=concurrent_imports, args=(50, 0.1))
    p.start()
    p.join()
    assert_that(p.exitcode).is_equal_to(0)
