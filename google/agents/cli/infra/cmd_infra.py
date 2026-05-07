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

"""agents-cli infra command — infrastructure provisioning."""

from pathlib import Path

import click

from google.agents.cli._project import chdir_project_root
from google.agents.cli._tools import get_terraform_path
from google.agents.cli.infra._cicd_utils import run_terraform


@click.group("infra")
def infra_group():
    """Provision infrastructure for your agent project.

    \b
    Subcommands:
      single-project  Optional — custom infrastructure for a single GCP project
      cicd            Set up CI/CD pipelines and multi-environment infrastructure
      datastore       Provision datastore infrastructure for RAG agents
    """
    pass


@infra_group.command("single-project")
@click.option("--project", default=None, help="GCP project ID.")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Apply changes. Without this flag, only a plan is shown.",
)
def cmd_infra_single_project(project, apply_changes):
    """Provision single-project infrastructure (optional).

    Not required for basic deployments — `agents-cli deploy` works out of the
    box using smart defaults (default Compute Engine service account,
    on-the-fly resource provisioning). Run this when you need custom setup
    such as a dedicated service account, pre-provisioned secrets, or specific
    IAM bindings.

    \b
    By default, runs terraform init + terraform plan to preview changes.
    Use --apply to apply the changes.
    """
    chdir_project_root()

    get_terraform_path()

    tf_dir = Path("deployment/terraform/single-project")

    if not tf_dir.is_dir():
        raise click.ClickException(
            f"Terraform directory '{tf_dir}' not found.\n"
            "  Ensure your project was scaffolded with a deployment target that includes Terraform.\n"
            "  Run 'agents-cli scaffold enhance' to add deployment infrastructure."
        )

    extra_vars = {"project_id": project} if project else None
    run_terraform(tf_dir=tf_dir, apply=apply_changes, extra_vars=extra_vars)

    if not apply_changes:
        followup = "google-agents infra single-project --apply"
        if project:
            followup += f" --project {project}"
        click.echo(f"\nTo apply these changes, run:\n  {followup}")
