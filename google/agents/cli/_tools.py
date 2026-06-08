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
import shlex
import shutil
import subprocess
from functools import cache
from pathlib import Path

import click

_tool_paths: dict[str, str] = {}

_GCLOUD_RELATIVE_PATH = (
    Path("Google") / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"
)

# Default installation hints for common tools.
# These are used as fallbacks in require_tool when no specific hint is provided,
# ensuring helpful error messages even when tools are resolved implicitly (e.g. via run_resolved).
DEFAULT_INSTALL_HINTS = {
    "npx": "Install Node.js (https://nodejs.org/en/download) and try again.",
    "npm": "Install Node.js (https://nodejs.org/en/download) and try again.",
    "gcloud": "Install the Google Cloud SDK (https://cloud.google.com/sdk/docs/install) and ensure it is in your PATH.",
    "terraform": "Install Terraform (https://developer.hashicorp.com/terraform/downloads) and ensure it is in your PATH.",
    "gh": "Install the GitHub CLI (https://cli.github.com/) and ensure it is in your PATH.",
    "git": "Install Git (https://git-scm.com/downloads) and ensure it is in your PATH.",
}


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


def _is_windows() -> bool:
    """Returns True if the current operating system is Windows."""
    return os.name == "nt"


def _get_gcloud_fallback() -> str | None:
    """Check common installation paths for gcloud on Windows.

    This serves as a fallback when gcloud is not found on the PATH, which
    typically happens if the user opted not to add gcloud to the PATH during
    installation.
    """
    if not _is_windows():
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
    4. If not found and the tool is 'gcloud', attempts to find in common Windows fallback paths.
    5. If still not found, raises a `ToolNotFoundError` with an optional install hint.
    6. If found, caches the path and returns it.
    """
    if name in _tool_paths:
        return _tool_paths[name]

    path = shutil.which(name)

    if path is None and _is_windows():
        path = shutil.which(name, path=_get_cleaned_path())

    if path is None:
        if name == "gcloud":
            path = _get_gcloud_fallback()

        if path is None:
            msg = f"'{name}' is not installed or not on PATH."
            hint = install_hint or DEFAULT_INSTALL_HINTS.get(name, "")
            if hint:
                msg += f"\n  {hint}"
            raise ToolNotFoundError(msg)

    _tool_paths[name] = path
    return path


def run_npx_skills(args: list[str], spinner_msg: str) -> list[str]:
    """Run an npx skills command, streaming output in real-time.
    Always starts with ``["npx", "-y", SKILLS_NPX_PACKAGE]`` and appends
    the additional ``args`` provided.
    Streams stdout/stderr line-by-line, filtering npm/npx boilerplate.
    All non-noise lines are printed immediately. Only concise summary
    lines (e.g. "Installed 6 skills", "Found 6 skills") are collected
    for the end summary.
    Returns:
        A list of summary-worthy lines (short, no decorative content).
    Raises:
        click.ClickException: If the npx process exits non-zero.
    """
    from google.agents.cli._runner import popen_resolved
    from google.agents.cli._skills_check import SKILLS_NPX_PACKAGE

    full_args = ["npx", "-y", SKILLS_NPX_PACKAGE, *args]
    click.secho(f"  \u25b8 {shlex.join(full_args)}", fg="cyan", dim=True)

    summary_lines = []
    proc = popen_resolved(
        full_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # Read stdout line-by-line
    assert proc.stdout is not None
    for line in proc.stdout:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip npx download/cache noise
        if stripped.startswith("npm ") or stripped.startswith("npx:"):
            continue
        # Skip ASCII art banners (block characters)
        if any(ch in stripped for ch in "█╗╔║╚╝"):
            continue
        # Strip leading box-drawing / bullet prefixes to extract text
        clean = stripped.lstrip("┌┐└┘├┤│◇●◆✓─╮╯ ")
        if not clean:
            continue
        # Skip per-agent detail lines
        if clean.startswith(("universal:", "symlink", "overwrites:")):
            continue
        # Skip purely decorative headers (e.g. "Installation Summary ────")
        if "──" in clean:
            continue
        click.echo(f"  {clean}")
        # Collect concise summary-worthy lines for the recap
        if len(clean) < 80 and clean.startswith(
            ("Installed", "Found", "Done", "Removed", "Updated")
        ):
            summary_lines.append(clean)

    proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ""
        click.secho("  Error running npx skills:", fg="red")
        if stderr.strip():
            for line in stderr.strip().splitlines():
                click.echo(f"  {line}")
        raise click.ClickException("npx skills failed")

    return summary_lines
