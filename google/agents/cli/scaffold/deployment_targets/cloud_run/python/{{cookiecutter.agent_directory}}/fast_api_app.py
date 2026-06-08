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
import os
{%- if cookiecutter.is_a2a %}
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
{%- endif %}
{%- if cookiecutter.session_type == "cloud_sql" %}
from urllib.parse import quote
{%- endif %}

import google.auth
{%- if cookiecutter.is_a2a %}
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentExtension
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
)
{%- endif %}
from fastapi import FastAPI
{%- if cookiecutter.is_a2a %}
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
{%- else %}
from google.adk.cli.fast_api import get_fast_api_app
{%- endif %}
from google.cloud import logging as google_cloud_logging
{% if cookiecutter.session_type == "agent_platform_sessions" -%}
from vertexai import agent_engines
{% endif %}

{%- if cookiecutter.is_a2a %}
from {{cookiecutter.agent_directory}}.agent import app as adk_app
{%- endif %}
from {{cookiecutter.agent_directory}}.app_utils.telemetry import setup_telemetry
from {{cookiecutter.agent_directory}}.app_utils.typing import Feedback

setup_telemetry()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
{%- if not cookiecutter.is_a2a %}
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)
{%- endif %}

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")
{%- if cookiecutter.is_a2a %}
artifact_service = (
    GcsArtifactService(bucket_name=logs_bucket_name)
    if logs_bucket_name
    else InMemoryArtifactService()
)

runner = Runner(
    app=adk_app,
    artifact_service=artifact_service,
    session_service=InMemorySessionService(),
)

request_handler = DefaultRequestHandler(
    agent_executor=A2aAgentExecutor(runner=runner),
    task_store=InMemoryTaskStore(),
)

A2A_RPC_PATH = f"/a2a/{adk_app.name}"


async def build_dynamic_agent_card() -> AgentCard:
    """Builds the Agent Card dynamically from the root_agent."""
    agent_card_builder = AgentCardBuilder(
        agent=adk_app.root_agent,
        capabilities=AgentCapabilities(
            streaming=True,
            extensions=[
                AgentExtension(
                    uri="https://google.github.io/adk-docs/a2a/a2a-extension/",
                    description="Ability to use the new agent executor implementation",
                ),
            ],
        ),
        rpc_url=f"{os.getenv('APP_URL', 'http://0.0.0.0:8000')}{A2A_RPC_PATH}",
        agent_version=os.getenv("AGENT_VERSION", "0.1.0"),
    )
    agent_card = await agent_card_builder.build()
    return agent_card


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
    agent_card = await build_dynamic_agent_card()
    a2a_app = A2AFastAPIApplication(agent_card=agent_card, http_handler=request_handler)
    a2a_app.add_routes_to_app(
        app_instance,
        agent_card_url=f"{A2A_RPC_PATH}{AGENT_CARD_WELL_KNOWN_PATH}",
        rpc_url=A2A_RPC_PATH,
        extended_agent_card_url=f"{A2A_RPC_PATH}{EXTENDED_AGENT_CARD_PATH}",
    )
    yield


app = FastAPI(
    title="{{cookiecutter.project_name}}",
    description="API for interacting with the Agent {{cookiecutter.project_name}}",
    lifespan=lifespan,
)
{% else %}

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

{%- if cookiecutter.session_type == "cloud_sql" %}
# Cloud SQL session configuration
db_user = os.environ.get("DB_USER", "postgres")
db_name = os.environ.get("DB_NAME", "postgres")
db_pass = os.environ.get("DB_PASS")
instance_connection_name = os.environ.get("INSTANCE_CONNECTION_NAME")

session_service_uri = None
if instance_connection_name and db_pass:
    # Use Unix socket for Cloud SQL
    # URL-encode username and password to handle special characters (e.g., '[', '?', '#', '$')
    # These characters can cause URL parsing errors, especially '[' which triggers IPv6 validation
    encoded_user = quote(db_user, safe="")
    encoded_pass = quote(db_pass, safe="")
    # URL-encode the connection name to prevent colons from being misinterpreted
    encoded_instance = instance_connection_name.replace(":", "%3A")

    session_service_uri = (
        f"postgresql+asyncpg://{encoded_user}:{encoded_pass}@"
        f"/{db_name}"
        f"?host=/cloudsql/{encoded_instance}"
    )
{%- elif cookiecutter.session_type == "agent_platform_sessions" %}
# Agent Runtime session configuration
# Check if we should use in-memory session for testing (set USE_IN_MEMORY_SESSION=true for E2E tests)
use_in_memory_session = os.environ.get("USE_IN_MEMORY_SESSION", "").lower() in (
    "true",
    "1",
    "yes",
)

if use_in_memory_session:
    # Use in-memory session for local testing
    session_service_uri = None
else:
    # Use environment variable for agent name, default to project name
    default_agent_name = "{{cookiecutter.project_name}}"
    agent_name = os.environ.get("AGENT_ENGINE_SESSION_NAME", default_agent_name)

    # Check if an agent with this name already exists
    existing_agents = list(agent_engines.list(filter=f"display_name={agent_name}"))

    if existing_agents:
        # Use the existing agent
        agent_runtime = existing_agents[0]
    else:
        # Create a new agent if none exists
        agent_runtime = agent_engines.create(display_name=agent_name)

    session_service_uri = f"agentengine://{agent_runtime.resource_name}"
{%- else %}
# In-memory session configuration - no persistent storage
session_service_uri = None
{%- endif %}

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=True,
)
app.title = "{{cookiecutter.project_name}}"
app.description = "API for interacting with the Agent {{cookiecutter.project_name}}"
{% endif %}

@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
