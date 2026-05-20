# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
"""Cross-process file-backed memoization decorator.

Drop-in replacement for ``functools.cache`` that persists results to a file
guarded by a :class:`filelock.FileLock`, so that callers running in separate
processes (e.g. pytest-xdist workers) share cached values instead of each
recomputing the same result.
"""

import functools
import os
import pickle
import tempfile

from filelock import FileLock


def file_cache(filename: str):
    """Decorator providing cross-process memoization backed by a file.

    Works like ``functools.cache`` but persists results across processes via a
    pickle file. All positional and keyword arguments must be hashable and
    return values must be picklable.

    Parameters
    ----------
    filename:
        Path to the cache file. If a relative path is given, it is resolved
        under :func:`tempfile.gettempdir` so the cache survives a single
        machine across pytest sessions and is shared by all workers.
    """
    cache_path = filename if os.path.isabs(filename) else os.path.join(tempfile.gettempdir(), filename)
    lock_path = cache_path + ".lock"

    def decorator(func):
        in_memory = {}

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            if key in in_memory:
                return in_memory[key]

            with FileLock(lock_path):
                disk_cache = _load(cache_path)
                if key in disk_cache:
                    in_memory[key] = disk_cache[key]
                    return disk_cache[key]

                result = func(*args, **kwargs)
                disk_cache[key] = result
                _dump(cache_path, disk_cache)
                in_memory[key] = result
                return result

        def cache_clear():
            in_memory.clear()
            with FileLock(lock_path):
                if os.path.exists(cache_path):
                    os.remove(cache_path)

        wrapper.cache_clear = cache_clear
        wrapper.__wrapped__ = func
        return wrapper

    return decorator


def _load(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (EOFError, pickle.UnpicklingError):
        # Corrupted cache file — start fresh.
        return {}


def _dump(path, data):
    # Atomic write: dump to a temp file in the same directory, then rename.
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".file_cache_", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
