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
from pathlib import Path

import click

from google.agents.cli import _tools


def run(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    env: dict | None = None,
    capture: bool = False,
    print_cmd: bool = True,
    check: bool = True,
    check_err_msg: str | None = None,
    input_data: bytes | None = None,
    timeout: int | None = None,
    resolve_executable: bool = True,
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
        timeout: Timeout in seconds for the subprocess.
        resolve_executable: If True, resolve the executable path using require_tool.
            Defaults to True.


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
        result = run_resolved(
            args,
            resolve_executable=resolve_executable,
            capture_output=True,
            text=input_data is None,
            cwd=cwd,
            input=input_data,
            env=run_env,
            timeout=timeout,
        )
    else:
        result = run_resolved(
            args,
            resolve_executable=resolve_executable,
            cwd=cwd,
            input=input_data,
            env=run_env,
            timeout=timeout,
        )

    if check and result.returncode != 0:
        error_msg = check_err_msg or f"Command failed: {cmd_str}"
        raise click.ClickException(f"{error_msg} (exit code {result.returncode})")

    return result


def run_resolved(
    args: list[str], *, resolve_executable: bool = True, **kwargs
) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run with optional executable resolution.

    Args:
        args: Command and arguments as a list of strings.
        resolve_executable: If True, resolve the executable path using require_tool.
            Defaults to True.
        **kwargs: Additional keyword arguments passed to subprocess.run.

    Raises:
        ToolNotFoundError: If resolve_executable is True and the tool cannot be found.

    Returns:
        CompletedProcess instance.
    """
    if isinstance(args, str):
        raise ValueError("args must be a list of strings, not a single string.")

    if resolve_executable and args:
        executable = args[0]
        # Create a shallow copy to avoid modifying the original list passed by reference
        args = args.copy()
        args[0] = _tools.require_tool(executable)

    return subprocess.run(args, **kwargs)


def popen_resolved(
    args: list[str], *, resolve_executable: bool = True, **kwargs
) -> subprocess.Popen:
    """Wrapper around subprocess.Popen with optional executable resolution.

    Args:
        args: Command and arguments as a list of strings.
        resolve_executable: If True, resolve the executable path using require_tool.
            Defaults to True.
        **kwargs: Additional keyword arguments passed to subprocess.Popen.

    Raises:
        ToolNotFoundError: If resolve_executable is True and the tool cannot be found.

    Returns:
        Popen instance.
    """
    if isinstance(args, str):
        raise ValueError("args must be a list of strings, not a single string.")

    if resolve_executable and args:
        executable = args[0]
        # Create a shallow copy to avoid modifying the original list passed by reference
        args = args.copy()
        args[0] = _tools.require_tool(executable)

    return subprocess.Popen(args, **kwargs)
