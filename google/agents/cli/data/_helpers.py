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

"""Shared helpers for data/RAG commands."""

import subprocess

import click


def resolve_project_id(project: str | None) -> str | None:
    """Resolve project ID from flag or gcloud default."""
    if project:
        return project
    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def require_project_id(project: str | None) -> str:
    """Resolve project ID, raising ClickException if unresolvable."""
    project_id = resolve_project_id(project)
    if not project_id:
        raise click.ClickException(
            "Could not determine GCP project ID.\n"
            "  Use --project or set a default with: gcloud config set project <PROJECT_ID>"
        )
    return project_id


def require_rag_project(cfg):
    """Raise if the current project is not an agentic_rag project."""
    base_template = cfg.extra.get("base_template", "")
    create_params = cfg.extra.get("create_params", {})
    is_rag = (
        base_template == "agentic_rag"
        or cfg.requires_data_ingestion
        or create_params.get("include_data_ingestion", False)
    )
    if not is_rag:
        raise click.ClickException(
            "This command requires a project with RAG / data ingestion support.\n"
            f"  Current base_template: {base_template or 'not set'}\n\n"
            "  To add RAG capabilities to your project, run:\n"
            "    agents-cli scaffold enhance"
        )


def get_datastore_type(cfg):
    """Read datastore type from project config, checking both legacy and current paths."""
    create_params = cfg.extra.get("create_params", {})
    datastore = create_params.get("datastore", "") or cfg.extra.get("datastore_type", "")
    if datastore == "none":
        datastore = ""
    return datastore
