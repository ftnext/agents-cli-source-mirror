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

"""Show project configuration, paths, and CLI version."""

from __future__ import annotations

from pathlib import Path

import click

import google.agents.cli as _cli_pkg
from google.agents.cli.__init__ import __version__
from google.agents.cli._output import emit
from google.agents.cli._project import (
    check_cli_version,
    find_project_root,
    read_project_config,
)
from google.agents.cli._skills_check import get_installed_skills

_CLI_INSTALL_PATH = str(Path(_cli_pkg.__file__).parent)


def _print_installed_skills(
    skills: list[dict] | None,
) -> None:
    """Print installed skills summary."""
    if skills is None:
        click.echo("Installed skills:   (could not query)")
        return
    if not skills:
        click.echo("Installed skills:   none")
        return
    # Group by scope
    by_scope: dict[str, list[str]] = {}
    for s in skills:
        scope = s.get("scope", "unknown")
        by_scope.setdefault(scope, []).append(s["name"])
    for scope, names in sorted(by_scope.items()):
        click.echo(f"Installed skills:   {len(names)} ({scope})")
        for name in sorted(names):
            click.echo(f"  - {name}")


@click.command()
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def cmd_info(as_json: bool) -> None:
    """Show project configuration, paths, and CLI version."""
    installed_skills = get_installed_skills()
    project_root = find_project_root()
    if project_root is None:
        if as_json:
            emit(
                {
                    "cli_version": __version__,
                    "cli_install_path": _CLI_INSTALL_PATH,
                    "installed_skills": installed_skills,
                    "project": None,
                }
            )
        else:
            click.echo(f"CLI version:        {__version__}")
            click.echo(f"CLI install path:   {_CLI_INSTALL_PATH}")
            _print_installed_skills(installed_skills)
            click.echo()
            click.echo("No agent project found in the current directory or any parent.")
            click.echo("  Run this command from within a project, or create one:")
            click.echo("    agents-cli create my-agent")
        return

    cfg = read_project_config(str(project_root))
    check_cli_version(cfg)

    info = {
        "cli_version": __version__,
        "cli_install_path": _CLI_INSTALL_PATH,
        "installed_skills": installed_skills,
        "project_root": str(project_root),
        "project_name": cfg.project_name,
        "deployment_target": cfg.deployment_target,
        "agent_directory": cfg.agent_directory,
        "is_a2a": cfg.is_a2a,
        "region": cfg.region,
    }

    if as_json:
        emit(info)
        return

    click.echo(f"CLI version:        {__version__}")
    click.echo(f"CLI install path:   {_CLI_INSTALL_PATH}")
    _print_installed_skills(installed_skills)
    click.echo()
    click.echo(f"Project root:       {project_root}")
    click.echo(f"Project name:       {cfg.project_name or '(not set)'}")
    click.echo(f"Deployment target:  {cfg.deployment_target}")
    click.echo(f"Agent directory:    {cfg.agent_directory}")
    click.echo(f"Region:             {cfg.region}")
    if cfg.is_a2a:
        click.echo("A2A:                yes")
