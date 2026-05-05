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

"""Version checking utilities for the CLI."""

import logging
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import requests
from packaging import version as pkg_version
from rich.console import Console

console = Console()

PACKAGE_NAME = "google-agents-cli"
_UPDATE_CHECK_INTERVAL = 12 * 60 * 60  # 12 hours in seconds
_UPDATE_CHECK_STAMP = Path.home() / ".agents" / ".acli_update_check"


def _update_check_is_due() -> bool:
    """Return True if enough time has elapsed since the last check."""
    try:
        last = float(_UPDATE_CHECK_STAMP.read_text().strip())
        return (time.time() - last) > _UPDATE_CHECK_INTERVAL
    except (OSError, ValueError):
        return True


def _record_update_check() -> None:
    """Write the current timestamp to the stamp file."""
    try:
        _UPDATE_CHECK_STAMP.parent.mkdir(parents=True, exist_ok=True)
        _UPDATE_CHECK_STAMP.write_text(str(time.time()))
    except OSError:
        pass


def get_current_version() -> str:
    """Get the current installed version of the package."""
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        # For development environments where package isn't installed
        return "0.0.0"  # Default if version can't be determined


def get_latest_version() -> str:
    """Get the latest version available on PyPI."""
    try:
        response = requests.get(f"https://pypi.org/pypi/{PACKAGE_NAME}/json", timeout=2)
        if response.status_code == 200:
            return response.json()["info"]["version"]
        return "0.0.0"
    except Exception:
        return "0.0.0"  # Default if PyPI can't be reached


def check_for_updates() -> tuple[bool, str, str]:
    """Check if a newer version of the package is available.

    Returns:
        Tuple of (needs_update, current_version, latest_version)
    """
    current = get_current_version()
    latest = get_latest_version()

    needs_update = pkg_version.parse(latest) > pkg_version.parse(current)

    return needs_update, current, latest


def display_update_message() -> None:
    """Check for updates and display a message if an update is available."""
    if not _update_check_is_due():
        return

    try:
        needs_update, current, latest = check_for_updates()

        # We only record the check if we successfully queried it
        _record_update_check()

        if needs_update:
            console.print(
                f"\n[yellow]⚠️  Update available: {current} → {latest}[/]",
                highlight=False,
            )
            console.print(
                f"[yellow]Run `uv tool upgrade {PACKAGE_NAME}` to update.[/]",
                highlight=False,
            )
            console.print(
                f"[dim]If you installed differently: pip install --upgrade {PACKAGE_NAME} | pipx upgrade {PACKAGE_NAME}[/]",
                highlight=False,
            )
    except Exception as e:
        # Don't let version checking errors affect the CLI
        logging.debug(f"Error checking for updates: {e}")
