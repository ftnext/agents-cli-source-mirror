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

"""Project configuration reader for agent projects."""

from __future__ import annotations

import logging
import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import click


@dataclass
class ProjectConfig:
    """Configuration derived from pyproject.toml [tool.agents-cli]."""

    project_name: str = ""
    version: str = "0.0.0"
    deployment_target: str = "none"
    agent_directory: str = "app"
    is_a2a: bool = False
    requires_data_ingestion: bool = False
    region: str = "us-east1"
    extra: dict = field(default_factory=dict)


def read_project_config(project_dir: str | None = None) -> ProjectConfig:
    """Read project metadata from pyproject.toml.

    Looks for [tool.agents-cli] section. Falls back to
    sensible defaults if the file or section doesn't exist.

    Args:
        project_dir: Directory containing pyproject.toml.
            Defaults to current working directory.

    Returns:
        ProjectConfig with values from pyproject.toml or defaults.
    """
    root = Path(project_dir) if project_dir else Path.cwd()
    pyproject = root / "pyproject.toml"

    if not pyproject.exists():
        return ProjectConfig()

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    # Read project name and version from [project]
    project_section = data.get("project", {})
    project_name = project_section.get("name", "")
    version = project_section.get("version", "0.0.0")

    # Read ACLI config from [tool.agents-cli]
    acli = data.get("tool", {}).get("agents-cli", {})
    create_params = acli.get("create_params", {})

    return ProjectConfig(
        project_name=project_name,
        version=version,
        deployment_target=create_params.get("deployment_target", "none"),
        agent_directory=acli.get("agent_directory", "app"),
        is_a2a=create_params.get("is_a2a", False),
        requires_data_ingestion=create_params.get("include_data_ingestion", False),
        region=acli.get("region", "us-east1"),
        extra={
            k: v
            for k, v in acli.items()
            if k
            not in {
                "agent_directory",
                "region",
            }
        },
    )


def check_cli_version(cfg: ProjectConfig) -> None:
    """Warn if the running CLI version doesn't match the version that scaffolded the project.

    Compares ``acli_version`` from ``[tool.agents-cli]`` with the running
    ``__version__``.  Emits a warning with upgrade guidance when there is a
    mismatch; never blocks execution.
    """
    acli_version = cfg.extra.get("acli_version")
    if not acli_version:
        return

    from google.agents.cli import __version__

    def _parse(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    try:
        project_ver = _parse(acli_version)
        cli_ver = _parse(__version__)
    except Exception:
        return

    if cli_ver < project_ver:
        click.echo(
            f"\n⚠️  Version mismatch: project was scaffolded with agents-cli {acli_version},"
            f" running {__version__}.\n"
            f"   Upgrade the CLI: uv tool install google-agents-cli@{acli_version}\n"
        )
    elif cli_ver > project_ver:
        click.echo(
            f"\n⚠️  Version mismatch: project was scaffolded with agents-cli {acli_version},"
            f" running {__version__}.\n"
            "   Upgrade the project: agents-cli scaffold upgrade\n"
        )


def find_project_root(dir: Path | None = None) -> Path | None:
    """Find the project root by walking up looking for pyproject.toml with [tool.agents-cli]."""
    if dir is None:
        dir = Path.cwd()
    for parent in [dir, *dir.parents]:
        pyproj = parent / "pyproject.toml"
        if pyproj.exists():
            try:
                with open(pyproj, "rb") as f:
                    data = tomllib.load(f)
                if "agents-cli" in data.get("tool", {}):
                    return parent
            except Exception:
                # If it fails to parse or is corrupted, skip it
                pass
    return None


def is_project_moved() -> bool:
    """Check if the project has been moved by comparing the current path with .venv/bin/activate."""
    root = find_project_root(Path.cwd())
    if not root:
        return False

    venv_dir = root / ".venv"
    activate_script = venv_dir / "bin" / "activate"
    if not activate_script.exists():
        return False

    try:
        with open(activate_script, encoding="utf-8") as f:
            for line in f:
                if line.startswith("VIRTUAL_ENV="):
                    stored_path_str = line.split("=", 1)[1].strip().strip("'\"")
                    stored_path = Path(stored_path_str).resolve()
                    current_path = venv_dir.resolve()
                    return stored_path != current_path
    except Exception as e:
        logging.warning(f"Error checking if project moved: {e}")
    return False


# ---------------------------------------------------------------------------
# Prerequisite guards — reusable checks for CLI commands
# ---------------------------------------------------------------------------


def chdir_project_root(dir: Path | None = None) -> None:
    """
    Locate the project root relative to the supplied directory and chdir to it.
    Raise if no root is found.
    """
    if dir is None:
        dir = Path.cwd()
    root = find_project_root(dir)
    if not root:
        raise click.ClickException(
            "No pyproject.toml found in the current directory or its parents.\n"
            "  Run this command from your project root, or create a project first:\n"
            "    agents-cli create my-agent"
        )
    click.echo(f"Using project root directory: {root}")
    os.chdir(root)


def require_agent_directory(cfg: ProjectConfig) -> None:
    """
    Raise if the configured agent_directory doesn't exist.
    Assumes cwd is the project root.
    """
    agent_path = Path(cfg.agent_directory)
    if not agent_path.is_dir():
        raise click.ClickException(
            f"Agent directory '{cfg.agent_directory}' not found.\n"
            "  Ensure you're in the project root and that the directory exists.\n"
            "  The agent_directory is configured in [tool.agents-cli] in pyproject.toml."
        )


def require_deployment_target(cfg: ProjectConfig) -> None:
    """Raise if no deployment target is configured."""
    if cfg.deployment_target in ("none", ""):
        raise click.ClickException(
            "No deployment target configured.\n"
            "  Set deployment_target in [tool.agents-cli] in pyproject.toml,\n"
            "  or add deployment support to your project:\n"
            "    agents-cli scaffold enhance"
        )


def require_a2a_project(cfg: ProjectConfig) -> None:
    """Raise if the project is not an A2A agent."""
    if not cfg.is_a2a:
        raise click.ClickException(
            "This command requires an A2A agent project (is_a2a = true).\n"
            "  To add A2A support to your project, run:\n"
            "    agents-cli scaffold enhance"
        )


_tool_paths: dict[str, str] = {}


def require_tool(name: str, install_hint: str = "") -> str:
    """Raise if a CLI tool is not found on PATH. Returns the path if found."""
    if name not in _tool_paths:
        path = shutil.which(name)
        if path is None:
            msg = f"'{name}' is not installed or not on PATH."
            if install_hint:
                msg += f"\n  {install_hint}"
            raise click.ClickException(msg)
        _tool_paths[name] = path
    return _tool_paths[name]


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
