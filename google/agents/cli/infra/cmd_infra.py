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

from google.agents.cli._project import chdir_project_root, require_tool
from google.agents.cli._runner import run


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
def cmd_infra_single_project(project):
    """Provision single-project infrastructure (optional).

    Not required for basic deployments — `agents-cli deploy` works out of the
    box using smart defaults (default Compute Engine service account,
    on-the-fly resource provisioning). Run this when you need custom setup
    such as a dedicated service account, pre-provisioned secrets, or specific
    IAM bindings.

    \b
    Runs: terraform init + terraform apply in deployment/terraform/single-project/
    """
    chdir_project_root()

    require_tool(
        "terraform",
        "Install Terraform: https://developer.hashicorp.com/terraform/install",
    )

    tf_dir = "deployment/terraform/single-project"

    if not Path(tf_dir).is_dir():
        raise click.ClickException(
            f"Terraform directory '{tf_dir}' not found.\n"
            "  Ensure your project was scaffolded with a deployment target that includes Terraform.\n"
            "  Run 'agents-cli scaffold enhance' to add deployment infrastructure."
        )

    run(
        ["terraform", f"-chdir={tf_dir}", "init"],
        check_err_msg="Terraform init failed for single-project",
    )

    apply_args = ["terraform", f"-chdir={tf_dir}", "apply", "-auto-approve"]
    if project:
        apply_args.extend(["-var", f"project_id={project}"])

    run(apply_args, check_err_msg="Terraform apply failed for single-project")
