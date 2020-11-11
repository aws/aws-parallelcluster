# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import os


class Cache:
    """Simple utility class providing a cache mechanism for expensive functions."""

    cache = {}

    @staticmethod
    def enabled():
        """Tell if the cache is enabled."""
        return not os.environ.get("PCLUSTER_CACHE_DISABLED")

    @staticmethod
    def clear():
        """Clear the content of cache."""
        Cache.cache.clear()

    @staticmethod
    def cached(function):
        """
        Decorate a function to make it use a results cache based on passed arguments.

        Note: all arguments must be hashable for this function to work properly.
        """

        def wrapper(*args, **kwargs):
            cache_key = "{0}_{1}".format(str(args), str(kwargs))

            if cache_key in Cache.cache and Cache.enabled():
                return Cache.cache[cache_key]
            else:
                rv = function(*args, **kwargs)
                if Cache.enabled():
                    Cache.cache[cache_key] = rv
                return rv

        return wrapper
