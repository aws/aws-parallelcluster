# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License is
# located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or
# implied. See the License for the specific language governing permissions and
# limitations under the License.
"""
This module defines middleware functions for command line operations.
This allows the ability to provide custom logic either before or
after running an operation by specifying the name of the operation,
and then calling the function that is provided as the first argument
and passing the **kwargs provided.
"""

import time
import json


def list_clusters(func, _body, kwargs):
    time_func = kwargs.pop('time', False)
    start = time.time()
    ret = func(**kwargs)
    if time_func:
        ret['time'] = f"{time.time() - start} ms"
        print(json.dumps(ret, indent=2))
        return None  # supress default print
    else:
        return ret
