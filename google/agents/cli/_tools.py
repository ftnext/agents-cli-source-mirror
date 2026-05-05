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

"""Tool resolution utilities."""

import os
import shutil
from functools import cache
from pathlib import Path

import click

_tool_paths: dict[str, str] = {}

_GCLOUD_RELATIVE_PATH = (
    Path("Google") / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"
)


class ToolNotFoundError(click.ClickException):
    """Raised when a required external tool is not found on PATH."""

    pass


@cache
def _get_cleaned_path() -> str:
    """Returns a cleaned and expanded version of the PATH environment variable.

    This function performs the following steps:
    1. Splits the PATH environment variable using the OS-specific path separator.
    2. Strips quotes from each path segment.
    3. Filters out empty path segments.
    4. Expands environment variables (like $HOME or %USERPROFILE%) within each segment.
    5. Reconstructs the PATH string with the cleaned segments.
    """
    raw_path = os.environ.get("PATH", "")
    parts = raw_path.split(os.pathsep)
    cleaned_parts = []

    for part in parts:
        # Strip quotes from each path segment.
        part = part.strip('"').strip("'")
        if not part:
            continue
        cleaned_parts.append(os.path.expandvars(part))
    return os.pathsep.join(cleaned_parts)


def _get_gcloud_fallback() -> str | None:
    """Check common installation paths for gcloud on Windows.

    This serves as a fallback when gcloud is not found on the PATH, which
    typically happens if the user opted not to add gcloud to the PATH during
    installation.
    """
    if os.name != "nt":
        return None

    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    program_files_x86 = Path(
        os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")
    )

    possible_paths = [
        local_app_data / _GCLOUD_RELATIVE_PATH,
        program_files_x86 / _GCLOUD_RELATIVE_PATH,
        program_files / _GCLOUD_RELATIVE_PATH,
    ]
    for p in possible_paths:
        if p.exists():
            return str(p)
    return None


def require_tool(name: str, install_hint: str = "") -> str:
    """Finds a required external tool on the system PATH and returns its path.

    This function performs the following steps:
    1. Checks if the tool's path is already cached in `_tool_paths`.
    2. If not cached, searches for the tool using `shutil.which` with the default PATH.
    3. If not found and running on Windows, searches again using `shutil.which` with a cleaned PATH.
    4. If not found and the tool is 'gcloud', attempts to find it in common Windows fallback paths.
    5. If still not found, raises a `ToolNotFoundError` with an optional install hint.
    6. If found, caches the path and returns it.
    """
    if name in _tool_paths:
        return _tool_paths[name]

    path = shutil.which(name)

    if path is None and os.name == "nt":
        path = shutil.which(name, path=_get_cleaned_path())

    if path is None:
        if name == "gcloud":
            path = _get_gcloud_fallback()

        if path is None:
            msg = f"'{name}' is not installed or not on PATH."
            if install_hint:
                msg += f"\n  {install_hint}"
            raise ToolNotFoundError(msg)

    _tool_paths[name] = path
    return path


def get_npx_path() -> str:
    """Get the path to npx, raising an exception if not found."""
    return require_tool(
        "npx",
        install_hint="Install Node.js (https://nodejs.org/en/download) and try again.",
    )


def get_npm_path() -> str:
    """Get the path to npm, raising an exception if not found."""
    return require_tool(
        "npm",
        install_hint="Install Node.js (https://nodejs.org/en/download) and try again.",
    )


def get_gcloud_path() -> str:
    """Get the path to gcloud, raising an exception if not found."""
    return require_tool(
        "gcloud",
        install_hint="Install the Google Cloud SDK (https://cloud.google.com/sdk/docs/install) and ensure it is in your PATH.",
    )


def get_terraform_path() -> str:
    """Get the path to terraform, raising an exception if not found."""
    return require_tool(
        "terraform",
        install_hint="Install Terraform (https://developer.hashicorp.com/terraform/downloads) and ensure it is in your PATH.",
    )


def get_gh_path() -> str:
    """Get the path to gh, raising an exception if not found."""
    return require_tool(
        "gh",
        install_hint="Install the GitHub CLI (https://cli.github.com/) and ensure it is in your PATH.",
    )


def get_git_path() -> str:
    """Get the path to git, raising an exception if not found."""
    return require_tool(
        "git",
        install_hint="Install Git (https://git-scm.com/downloads) and ensure it is in your PATH.",
    )
