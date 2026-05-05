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

"""agents-cli login / status commands."""

import click

from google.agents.cli.auth import (
    is_authenticated,
    run_auth_step,
)


@click.command("login")
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    default=False,
    help="Enable interactive authentication (required for login).",
)
@click.option(
    "--status",
    is_flag=True,
    default=False,
    help="Show authentication status.",
)
def cmd_login(interactive: bool, status: bool):
    """Authenticate with Google Cloud or AI Studio. Requires --interactive (-i)."""
    if status:
        click.echo()
        click.secho("Status", fg="cyan", bold=True)
        click.echo()

        click.secho("Authentication", bold=True)
        click.echo()
        authed, display = is_authenticated()
        if authed:
            click.secho(f"  Authenticated as {display}", fg="green")
        else:
            click.secho("  Not authenticated", fg="yellow")
            click.echo("    Run 'agents-cli login -i' to authenticate.")
        click.echo()
        return

    if not interactive:
        raise click.UsageError(
            "'login' requires interactive mode. Pass -i / --interactive to authenticate."
        )
    click.echo()
    click.secho("Authentication", fg="cyan", bold=True)
    click.echo()
    run_auth_step()
