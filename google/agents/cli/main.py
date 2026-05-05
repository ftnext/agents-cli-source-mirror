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

"""Root Click group for the 'agents-cli' CLI."""

import os
import sys
import traceback

import click
from rich.console import Console

from google.agents.cli.__init__ import __version__
from google.agents.cli._click import patch_source_in_help
from google.agents.cli._project import is_project_moved
from google.agents.cli._tools import require_tool
from google.agents.cli.data.cmd_data_ingestion import cmd_data_ingestion
from google.agents.cli.deploy.cmd_deploy import cmd_deploy
from google.agents.cli.dev.cmd_install import cmd_install
from google.agents.cli.dev.cmd_lint import cmd_lint
from google.agents.cli.dev.cmd_playground import cmd_playground
from google.agents.cli.eval.cmd_compare import cmd_compare
from google.agents.cli.eval.cmd_eval import cmd_eval
from google.agents.cli.info.cmd_info import cmd_info
from google.agents.cli.infra.cmd_cicd import setup_cicd
from google.agents.cli.infra.cmd_datastore import cmd_infra_datastore
from google.agents.cli.infra.cmd_infra import infra_group
from google.agents.cli.publish.cmd_publish import publish_group
from google.agents.cli.run.cmd_run import cmd_run
from google.agents.cli.scaffold.commands.create import create as cmd_create
from google.agents.cli.scaffold.commands.enhance import enhance as cmd_enhance
from google.agents.cli.scaffold.commands.upgrade import upgrade as cmd_upgrade
from google.agents.cli.setup.cmd_auth import cmd_login
from google.agents.cli.setup.cmd_setup import cmd_setup
from google.agents.cli.setup.cmd_update import cmd_update


def _print_is_project_moved_tip() -> None:
    message = (
        "\n💡 Tip: It looks like the project folder may have been moved or renamed."
        " Try running `agents-cli install --clean` to reset the environment, then"
        " re-run your original command"
    )
    if is_project_moved():
        Console().print(message, style="cyan")


class _MainGroup(click.Group):
    """Click group that prints full tracebacks on unhandled exceptions."""

    def invoke(self, ctx: click.Context) -> None:
        try:
            super().invoke(ctx)
        except click.exceptions.Exit:
            raise
        except click.ClickException:
            click.echo(f"agents-cli v{__version__}", err=True)
            _print_is_project_moved_tip()
            raise
        except KeyboardInterrupt:
            Console().print(f"\nagents-cli v{__version__}", style="dim")
            Console().print("Operation cancelled by user", style="yellow")
            ctx.exit(130)
        except Exception:
            click.echo(f"agents-cli v{__version__}", err=True)
            _print_is_project_moved_tip()
            traceback.print_exc()
            ctx.exit(1)


@click.group(cls=_MainGroup)
@click.version_option(version=__version__, prog_name="agents-cli")
def main():
    """Agents CLI — Agent Development Lifecycle toolchain.

    Build, evaluate, and deploy ADK agents with a single unified CLI.

    \b
    Quick start:
      agents-cli setup                 Install skills to your coding agent
      agents-cli create my-agent       Create a new agent project
      agents-cli playground            Start the local playground
      agents-cli scaffold enhance .    Add deployment/CI-CD to a project
      agents-cli eval run              Run evaluations
      agents-cli deploy                Deploy the agent
    """
    # Disable gcloud interactive prompts for all CLI subprocesses
    # unless the user explicitly passes --interactive / -i.
    if "--interactive" not in sys.argv and "-i" not in sys.argv:
        os.environ["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"

    from google.agents.cli._skills_check import check_skills_version
    from google.agents.cli.scaffold.utils.version import display_update_message

    display_update_message()
    check_skills_version()
    require_tool("uv")


# Setup commands
main.add_command(cmd_setup, "setup")
main.add_command(cmd_update, "update")

# Auth commands
main.add_command(cmd_login, "login")


# Scaffold command group
@click.group("scaffold")
def scaffold_group():
    """Scaffold, enhance, and upgrade agent projects.

    \b
    Subcommands:
      create   Create a new agent project
      enhance  Add deployment target or CI/CD to an existing project
      upgrade  Upgrade project to a newer agents-cli version
    """


scaffold_group.add_command(cmd_create, "create")
scaffold_group.add_command(cmd_enhance, "enhance")
scaffold_group.add_command(cmd_upgrade, "upgrade")
main.add_command(scaffold_group)

# Top-level alias: agents-cli create → agents-cli scaffold create
main.add_command(cmd_create, "create")

# Dev commands
main.add_command(cmd_playground, "playground")
main.add_command(cmd_run, "run")
main.add_command(cmd_lint, "lint")
main.add_command(cmd_install, "install")

# Data commands
main.add_command(cmd_data_ingestion, "data-ingestion")


# Eval commands
@click.group("eval")
def eval_group():
    """Evaluate agents and compare results.

    \b
    Subcommands:
      run      Run agent evaluations
      compare  Compare two eval result JSON files
    """
    pass


eval_group.add_command(cmd_eval, "run")
eval_group.add_command(cmd_compare, "compare")
main.add_command(eval_group)

# Deploy commands
main.add_command(cmd_deploy, "deploy")
main.add_command(publish_group)

# Infra commands (infra single-project + infra cicd + infra datastore)
main.add_command(infra_group)
infra_group.add_command(setup_cicd, "cicd")
infra_group.add_command(cmd_infra_datastore, "datastore")

# Info command
main.add_command(cmd_info, "info")

# Patch all commands to show source file in --help
patch_source_in_help(main)


if __name__ == "__main__":
    main()
