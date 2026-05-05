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

"""Subprocess helpers for agents CLI."""

import os
import shlex
import subprocess
import sys

import click


def run(
    args: list[str],
    *,
    cwd: str | None = None,
    env: dict | None = None,
    capture: bool = False,
    print_cmd: bool = True,
    check: bool = True,
    check_err_msg: str | None = None,
    input_data: bytes | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess, streaming output by default.

    Args:
        args: Command and arguments.
        cwd: Working directory for the subprocess.
        env: Extra environment variables. Merged with os.environ if provided.
        capture: If True, capture stdout/stderr instead of streaming.
            Defaults to False.
        print_cmd: If True, print the command before executing.
            Defaults to True.
        check: If True, raise ClickException on non-zero exit.
            Defaults to True.
        check_err_msg: Error message prefix for check failures.
        input_data: Bytes to feed to stdin of the subprocess.

    Returns:
        CompletedProcess instance.
    """
    cmd_str = shlex.join(args)
    if print_cmd:
        click.secho(f"  ▸ {cmd_str}", fg="cyan", dim=True)

    run_env = None
    if env is not None:
        run_env = {**os.environ, **env}

    if capture:
        result = subprocess.run(
            args,
            capture_output=True,
            text=input_data is None,
            cwd=cwd,
            input=input_data,
            env=run_env,
            timeout=timeout,
        )
    else:
        result = subprocess.run(
            args,
            stdout=sys.stdout,
            stderr=sys.stderr,
            cwd=cwd,
            input=input_data,
            env=run_env,
            timeout=timeout,
        )

    if check and result.returncode != 0:
        error_msg = check_err_msg or f"Command failed: {cmd_str}"
        raise click.ClickException(f"{error_msg} (exit code {result.returncode})")

    return result
