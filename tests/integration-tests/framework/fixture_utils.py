#  Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import functools
import logging
import os
import pickle
import time
from dataclasses import dataclass
from inspect import getfullargspec, isgeneratorfunction
from pathlib import Path
from typing import Any, Callable

import pytest
from filelock import FileLock
from xdist import get_xdist_worker_id


@dataclass
class SharedFixtureData:
    """Represent the object holding the data of a shared fixture."""

    owning_xdist_worker_id: str
    counter: int = 0
    fixture_return_value: Any = None


class SharedFixture:
    """
    Define the methods to implement fixtures that can be shared across multiple pytest-dist processes.

    Synchronization is implemented through file locking.
    Fixture data is serialized to a file, together with a counter for the number of processes that are consuming
    the shared fixture. Only when such counter reaches 0 the actual fixture clean-up code is invoked.
    """

    def __init__(self, name: str, shared_save_location: Path, fixture_func: Callable, xdist_worker_id: str):
        self.name = name
        self.shared_save_location = shared_save_location
        self.fixture_func = fixture_func
        self.xdist_worker_id = xdist_worker_id
        self._lock_file = shared_save_location / f"{name}.lock"
        self._fixture_file = shared_save_location / f"{name}.fixture"
        self._generator = None

    def acquire(self) -> SharedFixtureData:
        """
        Acquire the shared fixture.

        Fixture is created only the first time you acquire it.
        """
        logging.info("Acquiring shared fixture %s", self.name)
        with FileLock(self._lock_file):
            data = self._load_fixture_data()
            data.counter = data.counter + 1
            self._save_fixture_data(data)
            return data

    def release(self):
        """
        Release a shared fixture.

        The fixture is cleaned-up only when the last process releases it.
        """
        with FileLock(self._lock_file):
            data = self._load_fixture_data()
            if self.xdist_worker_id != data.owning_xdist_worker_id:
                data.counter = data.counter - 1
                logging.info("Releasing shared fixture %s. Currently in use by %d processes", self.name, data.counter)
                self._save_fixture_data(data)
                return

        if data.counter > 1:
            logging.info(
                "Waiting for all processes to release shared fixture %s, currently in use by %d processes",
                self.name,
                data.counter,
            )
            time.sleep(60)
            self.release()
        else:
            logging.info("Deleting shared fixture %s.", self.name)
            os.remove(self._fixture_file)
            if self._generator:
                try:
                    # This is required to run the fixture cleanup code after the yield statement.
                    # This invocation will always throw a StopIteration exception.
                    next(self._generator)
                except StopIteration:
                    pass

    def _load_fixture_data(self) -> SharedFixtureData:
        try:
            with open(self._fixture_file, "rb") as f:
                fixture_data = pickle.load(f)
                logging.info("Loaded fixture data: %s", fixture_data)
                return fixture_data
        except (EOFError, FileNotFoundError):
            return SharedFixtureData(
                fixture_return_value=self._invoke_fixture(), owning_xdist_worker_id=self.xdist_worker_id
            )

    def _save_fixture_data(self, data: SharedFixtureData):
        logging.info("Saving fixture data: %s", data)
        with open(self._fixture_file, "wb+") as f:
            pickle.dump(data, f)

    def _invoke_fixture(self):
        logging.info("Initializing fixture data for %s", self.name)
        # Fixtures with yield and clean-up code are implemented as python generators.
        # In such cases we need to
        if isgeneratorfunction(self.fixture_func):
            self._generator = self.fixture_func()
            return next(self._generator)
        else:
            return self.fixture_func()


def xdist_session_fixture(**pytest_fixture_args):
    """
    Create a fixture that is shared across multiple pytest-xdist processes.

    Use this as you'd do for a normal @pytest.fixture(scope="session", autouse=True). The main difference is that when
    @xdist_session_fixture() is used the fixture code is executed only for the first pytest-xdist process that
    requests it, while later invocations will obtain a cached value.

    IMPORTANT: in case this fixture is not used with autouse=True, therefore the initialization is delayed until the
    first test/fixture requires it, this could in rare circumstances lead to dead locks. This is due to the fact that
    not all shared fixtures are owned by the same xdist process and the owning process is responsible to wait for
    all other processes to release the fixture before invoking the clean-up code.
    """

    def _xdist_session_fixture_decorator(func):
        @pytest.fixture(scope="session", **pytest_fixture_args)
        @functools.wraps(func)
        def _xdist_session_fixture(request, *args, **kwargs):
            base_dir = f"{request.config.getoption('output_dir')}/tmp/shared_fixtures"
            os.makedirs(base_dir, exist_ok=True)
            if "request" in getfullargspec(func).args:
                kwargs["request"] = request
            shared_fixture = SharedFixture(
                name=func.__name__,
                shared_save_location=Path(f"{request.config.getoption('output_dir')}/tmp/shared_fixtures"),
                fixture_func=functools.partial(func, *args, **kwargs),
                xdist_worker_id=get_xdist_worker_id(request),
            )
            yield shared_fixture.acquire().fixture_return_value
            shared_fixture.release()

        return _xdist_session_fixture

    return _xdist_session_fixture_decorator
