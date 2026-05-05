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

"""Utilities for running shell commands with cross-platform compatibility."""

from __future__ import annotations

import subprocess

from google.agents.cli._tools import get_gcloud_path


def run_gcloud_command(
    args: list[str],
    check: bool = True,
    capture_output: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Run a gcloud command with Windows compatibility.

    Automatically handles:
    - Resolving the full path to gcloud executable

    Args:
        args: Command arguments (without 'gcloud' prefix, e.g., ['config', 'get-value', 'account'])
        check: If True, raise CalledProcessError on non-zero exit
        capture_output: If True, capture stdout and stderr
        timeout: Optional timeout in seconds

    Returns:
        CompletedProcess instance
    """
    cmd = [get_gcloud_path(), *args]
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
