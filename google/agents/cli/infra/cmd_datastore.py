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

"""agents-cli infra datastore command — provision datastore infrastructure."""

from pathlib import Path

import click

from google.agents.cli._project import (
    chdir_project_root,
    read_project_config,
    require_tool,
)
from google.agents.cli._runner import run
from google.agents.cli.data._helpers import (
    get_datastore_type,
    require_project_id,
    require_rag_project,
    resolve_project_id,
)


def _upload_sample_data(project, cfg):
    """Upload sample_data/ to the GCS docs bucket if available."""
    sample_dir = Path("sample_data")
    if not sample_dir.is_dir() or not any(sample_dir.iterdir()):
        return
    project_id = resolve_project_id(project)
    if not project_id:
        click.echo(
            "⚠️  Skipping sample data upload: could not determine GCP project ID.\n"
            "  Use --project or set a default with: gcloud config set project <PROJECT_ID>"
        )
        return
    bucket = f"gs://{project_id}-{cfg.project_name}-docs"
    click.echo(f"📤 Uploading sample data to {bucket}...")
    run(
        ["gcloud", "storage", "cp", "-r", "sample_data/*", f"{bucket}/"],
        check_err_msg="Sample data upload failed",
    )


@click.command("datastore")
@click.option("--project", default=None, help="GCP project ID.")
@click.option("--region", default=None, help="GCP region.")
def cmd_infra_datastore(project, region):
    """Provision datastore infrastructure for RAG agents.

    \b
    Reads datastore_type from project config and runs the appropriate
    Terraform targets to set up the data backend.
    """
    chdir_project_root()
    cfg = read_project_config()
    require_rag_project(cfg)
    region = region or cfg.region

    datastore_type = get_datastore_type(cfg)

    if not datastore_type:
        raise click.ClickException(
            "No datastore type configured. "
            "Set datastore under [tool.agents-cli.create_params] in pyproject.toml."
        )

    project_id = require_project_id(project)
    var_args = ["-var", f"project_id={project_id}"]

    require_tool(
        "terraform",
        "Install Terraform: https://developer.hashicorp.com/terraform/install",
    )

    tf_dir = "deployment/terraform/single-project"
    tf_base = ["terraform", f"-chdir={tf_dir}"]

    # Init terraform
    run([*tf_base, "init"], check_err_msg="Terraform init failed")

    if datastore_type == "agent_platform_vector_search":
        click.echo("🔧 Provisioning Agent Platform Vector Search datastore...")
        targets = [
            "-target=null_resource.vector_search_collection",
        ]
        run(
            [*tf_base, "apply", "-auto-approve", *var_args, *targets],
            check_err_msg="Agent Platform Vector Search setup failed",
        )

    elif datastore_type == "agent_platform_search":
        click.echo("🔧 Provisioning Agent Platform Search datastore...")
        run(
            [
                *tf_base,
                "apply",
                "-auto-approve",
                *var_args,
                "-target=google_discovery_engine_search_engine.search_engine",
            ],
            check_err_msg="Agent Platform Search setup failed",
        )

        _upload_sample_data(project, cfg)

    else:
        raise click.ClickException(
            f"Unknown datastore_type: {datastore_type}. "
            "Supported: agent_platform_vector_search, agent_platform_search."
        )

    click.echo("✅ Datastore infrastructure provisioned.")
