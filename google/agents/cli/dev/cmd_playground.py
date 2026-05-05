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

"""agents-cli playground command — start local agent playground."""

import click
from rich.console import Console
from rich.panel import Panel

from google.agents.cli._project import (
    chdir_project_root,
    read_project_config,
    require_agent_directory,
)
from google.agents.cli._runner import run

_console = Console()


@click.command("playground")
@click.option("--port", default=8080, help="Port for the playground server.")
@click.option("--host", default="127.0.0.1", help="Host the server binds to.")
@click.option(
    "--reload_agents/--no-reload_agents",
    default=True,
    help="Enable / disable live reload when agent code changes.",
)
def cmd_playground(port, host, reload_agents):
    """Start the local agent playground.

    \b
    Runs: uv run adk web . --host HOST --port PORT [--reload_agents]
    """
    chdir_project_root()
    cfg = read_project_config()
    require_agent_directory(cfg)

    # adk web doesn't auto-select the agent — pre-fill it via ?app= so the
    # URL we print drops the user straight into their agent.
    browser_host = "localhost" if host == "0.0.0.0" else host
    url = f"http://{browser_host}:{port}/dev-ui/?app={cfg.agent_directory}"
    _print_banner(url)

    args = ["uv", "run", "adk", "web", ".", "--host", host, "--port", str(port)]
    if reload_agents:
        args.append("--reload_agents")
    run(args, check_err_msg="Failed to start playground")


def _print_banner(url: str) -> None:
    """Print a styled banner with a clickable URL pointing at the agent."""
    body = (
        "[bold cyan]Starting your agent playground...[/]\n"
        "\n"
        f"[bold]Will be available at:[/]  [green underline]{url}[/]"
    )
    _console.print(Panel(body, border_style="cyan"))
