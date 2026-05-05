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

"""agents-cli update command — update skills via npx skills CLI."""

import click

from google.agents.cli._runner import run
from google.agents.cli._skills_check import SKILLS_NPX_PACKAGE
from google.agents.cli._trust import require_confirmation
from google.agents.cli.setup.cmd_setup import _run_npx_skills


@click.command("update")
@click.option(
    "--workspace",
    is_flag=True,
    default=False,
    help="Update workspace-level skills instead of global.",
)
@require_confirmation("This will force-reinstall agents-cli skills to all detected IDEs.")
def cmd_update(workspace, yes, interactive):
    """Force reinstall agents skills to all detected coding agents.

    Updates all installed skills to their latest versions via npx skills.
    """
    click.echo()

    from google.agents.cli._project import get_npx_path

    npx_path = get_npx_path()
    args = [npx_path, "-y", SKILLS_NPX_PACKAGE, "update"]
    if not workspace:
        args.append("-g")

    _run_npx_skills(args, "Updating skills")

    click.echo()
    click.secho("Skills updated.", fg="green", bold=True)

    # Best-effort CLI upgrade
    click.echo()
    result = run(
        ["uv", "tool", "upgrade", "google-agents-cli"], capture=True, check=False
    )
    upgrade_out = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0 and "upgraded" in upgrade_out.lower():
        for line in (result.stdout or "").strip().splitlines():
            click.echo(f"  {line}")
    else:
        click.secho("  CLI already up to date.", dim=True)

    click.echo()
