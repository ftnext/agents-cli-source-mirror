# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""agents-cli install command — install project dependencies."""

import logging
import shutil

import click

from google.agents.cli._project import find_project_root
from google.agents.cli._runner import run


@click.command("install")
@click.option(
    "--clean",
    is_flag=True,
    help="Clean and fix the uv virtual environment. (For example, if the project folder is moved or renamed).",
)
def cmd_install(clean: bool):
    """Install project dependencies.

    Runs: uv sync
    """
    if clean:
        _delete_venv()
    run(["uv", "sync"], check_err_msg="Failed to install dependencies")


def _delete_venv():
    root = find_project_root()
    if not root:
        logging.warning(
            "Could not find project root: no pyproject.toml found in the current directory or any parent."
        )
        return

    venv_path = root / ".venv"

    if not venv_path.exists():
        return

    try:
        shutil.rmtree(venv_path)
    except Exception as e:
        logging.warning(f"Failed to remove venv: {e}")
