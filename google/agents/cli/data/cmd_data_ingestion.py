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

"""agents-cli data-ingestion command — run data ingestion pipelines."""

from pathlib import Path

import click

from google.agents.cli._project import (
    chdir_project_root,
    read_project_config,
)
from google.agents.cli._runner import run
from google.agents.cli.data._helpers import (
    get_datastore_type,
    require_project_id,
    require_rag_project,
)


@click.command("data-ingestion")
@click.option("--project", default=None, help="GCP project ID.")
@click.option("--region", default=None, help="GCP region.")
@click.option(
    "--vector-search-location",
    default="us-central1",
    help="Vector Search 2.0 location (defaults to us-central1). Also sets the BQ ingestion dataset region to keep it colocated with the collection.",
)
@click.option(
    "--collection-id", default=None, help="Collection ID for the data connector."
)
@click.option(
    "--remote",
    is_flag=True,
    default=False,
    help="Submit pipeline to Vertex AI Pipelines instead of running locally.",
)
def cmd_data_ingestion(project, region, vector_search_location, collection_id, remote):
    """Run data ingestion for RAG agents.

    \b
    For agent_platform_vector_search: submits the ingestion pipeline.
    For agent_platform_search: syncs the data connector.

    \b
    Regions: --vector-search-location (defaults to us-central1) sets
    both the Vector Search collection region and the BQ ingestion
    dataset region, kept colocated to avoid cross-region data movement.
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
    # Resolve collection ID: CLI flag > default convention from Terraform
    collection_id = collection_id or f"{cfg.project_name}-collection"

    if datastore_type == "agent_platform_vector_search":
        if not Path("data_ingestion").is_dir():
            raise click.ClickException(
                "data-ingestion requires a data_ingestion/ folder but it is missing.\n"
                "  Run 'agents-cli scaffold enhance' to restore it."
            )

        pipeline_dir = "data_ingestion/data_ingestion_pipeline"
        run(
            ["uv", "sync"],
            cwd=pipeline_dir,
            check_err_msg="Failed to sync data ingestion dependencies",
        )
        args = [
            "uv",
            "run",
            "python",
            "submit_pipeline.py",
            "--project",
            project_id,
            "--region",
            region,
            "--vector-search-location",
            vector_search_location,
            "--collection-id",
            collection_id,
        ]
        if remote:
            # Derive pipeline parameters from conventions matching Terraform
            service_account = (
                f"{cfg.project_name}-rag@{project_id}.iam.gserviceaccount.com"
            )
            pipeline_root = f"gs://{project_id}-{cfg.project_name}-rag"
            pipeline_name = cfg.project_name
            click.echo("📊 Submitting Vector Search ingestion pipeline...")
            args.extend(
                [
                    "--service-account",
                    service_account,
                    "--pipeline-root",
                    pipeline_root,
                    "--pipeline-name",
                    pipeline_name,
                ]
            )
        else:
            click.echo("📊 Running Vector Search ingestion pipeline locally...")
            args.append("--local")
        run(args, cwd=pipeline_dir, check_err_msg="Data ingestion pipeline failed")

    elif datastore_type == "agent_platform_search":
        click.echo("🔄 Syncing Agent Platform Search data...")
        sync_script = "deployment/terraform/scripts/start_connector_run.py"
        sync_args = [
            "uv",
            "run",
            sync_script,
            "--project",
            project_id,
            "--region",
            region,
            "--collection-id",
            collection_id,
        ]
        run(sync_args, check_err_msg="Data sync failed")

    else:
        raise click.ClickException(
            f"Unknown datastore_type: {datastore_type}. "
            "Supported: agent_platform_vector_search, agent_platform_search."
        )

    click.echo("✅ Data ingestion complete.")
