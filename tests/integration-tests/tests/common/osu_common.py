# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import os as os_lib
import pathlib

from constants import OSU_BENCHMARK_VERSION
from jinja2 import Environment, FileSystemLoader

OSU_COMMON_DATADIR = pathlib.Path(__file__).parent / "data/osu/"


def compile_osu(mpi_variant, remote_command_executor):
    init_script = render_jinja_template(
        template_file_path=OSU_COMMON_DATADIR / "init_osu_benchmarks.sh", osu_benchmark_version=OSU_BENCHMARK_VERSION
    )
    remote_command_executor.run_remote_script(
        str(init_script),
        args=[mpi_variant],
        hide=True,
        additional_files=[
            str(OSU_COMMON_DATADIR / f"osu-micro-benchmarks-{OSU_BENCHMARK_VERSION}.tgz"),
            str(OSU_COMMON_DATADIR / "config.guess"),
            str(OSU_COMMON_DATADIR / "config.sub"),
        ],
    )


def render_jinja_template(template_file_path, **kwargs):
    file_loader = FileSystemLoader(str(os_lib.path.dirname(template_file_path)))
    env = Environment(loader=file_loader)
    rendered_template = env.get_template(os_lib.path.basename(template_file_path)).render(**kwargs)
    with open(template_file_path, "w", encoding="utf-8") as f:
        f.write(rendered_template)
    return template_file_path
