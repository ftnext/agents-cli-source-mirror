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

"""Deploy agents to Agent Runtime.

De-templatized deploy module. All cookiecutter conditionals replaced
with runtime checks via ProjectConfig.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import subprocess
import warnings
from pathlib import Path
from typing import Any

import click
import vertexai
from google.cloud import resourcemanager_v3
from google.iam.v1 import iam_policy_pb2, policy_pb2
from vertexai._genai import _agent_engines_utils
from vertexai._genai.types import AgentEngine, AgentEngineConfig, IdentityType

from google.agents.cli._project import ProjectConfig, find_project_root
from google.agents.cli._runner import run_resolved
from google.agents.cli.deploy._operation import (
    METADATA_FILE,
    clear_operation,
    read_operation,
    write_operation,
)
from google.agents.cli.deploy._utils import parse_key_value_pairs, resolve_service_name
from google.agents.cli.scaffold.utils.language import get_project_version

# Suppress google-cloud-storage version compatibility warning
warnings.filterwarnings(
    "ignore", category=FutureWarning, module="google.cloud.aiplatform"
)


def generate_class_methods_from_agent(agent_instance: Any) -> list[dict[str, Any]]:
    """Generate method specs with schemas from agent's register_operations()."""
    registered_operations = _agent_engines_utils._get_registered_operations(
        agent=agent_instance
    )
    class_methods_spec = _agent_engines_utils._generate_class_methods_spec_or_raise(
        agent=agent_instance,
        operations=registered_operations,
    )
    return [
        _agent_engines_utils._to_dict(method_spec) for method_spec in class_methods_spec
    ]


_INTROSPECT_SCRIPT = """\
import asyncio, importlib, inspect, json, sys
sys.path.insert(0, ".")
module = importlib.import_module(sys.argv[1])
obj = getattr(module, sys.argv[2])
if inspect.iscoroutine(obj):
    obj = asyncio.run(obj)
from vertexai._genai import _agent_engines_utils
ops = _agent_engines_utils._get_registered_operations(agent=obj)
specs = _agent_engines_utils._generate_class_methods_spec_or_raise(agent=obj, operations=ops)
print(json.dumps([_agent_engines_utils._to_dict(s) for s in specs]))
"""


def _introspect_agent_via_subprocess(
    entrypoint_module: str, entrypoint_object: str
) -> list[dict[str, Any]]:
    """Import agent in project's venv and generate class_methods via subprocess.

    Runs the introspection in the project's own environment (via ``uv run``)
    so that the CLI itself does not need the project's dependencies installed.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(
        encoding="utf-8", mode="w", suffix=".py", delete=False
    ) as f:
        f.write(_INTROSPECT_SCRIPT)
        script_path = f.name
    try:
        result = run_resolved(
            ["uv", "run", "python", script_path, entrypoint_module, entrypoint_object],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(
            f"Failed to introspect agent {entrypoint_module}.{entrypoint_object}:\n"
            f"{e.stderr}"
        ) from e
    finally:
        os.unlink(script_path)


def parse_secrets(secrets_string: str | None) -> dict[str, dict[str, str]]:
    """Parse secrets from ENV_VAR=SECRET_ID or ENV_VAR=SECRET_ID:VERSION format."""
    raw = parse_key_value_pairs(secrets_string)
    result: dict[str, dict[str, str]] = {}
    for key, spec in raw.items():
        if ":" not in spec:
            secret_id, version = spec, "latest"
        else:
            secret_id, _, version = spec.rpartition(":")
        result[key] = {"secret": secret_id, "version": version}
    return result


def format_env_value(value: Any) -> str:
    """Format an env var value for display, masking secrets."""
    if isinstance(value, dict) and "secret" in value and "version" in value:
        return f"[secret:{value['secret']}:{value['version']}]"
    return str(value)


def _build_runtime_env_vars(
    *,
    set_env_vars: str | None,
    secrets: dict[str, dict[str, str]],
    num_workers: int,
) -> dict[str, Any]:
    """Assemble the runtime env vars for the deployed Agent Runtime.

    User ``--update-env-vars`` and ``--set-secrets`` win; everything else is an
    overridable default:

    - ``AGENT_VERSION`` — the pyproject.toml version, read at runtime by the A2A
      agent card. Read only when the user hasn't supplied a value, so an override
      skips the pyproject read and its missing-version warning.
    - ``NUM_WORKERS`` — defaults to ``num_workers``.
    - telemetry toggles — Cloud Trace export and prompt/response capture in spans.

    The deploy region is not baked in here: the agent reads ``GOOGLE_CLOUD_LOCATION``
    at runtime, which the Agent Engine platform injects.
    """
    env_vars: dict[str, Any] = parse_key_value_pairs(set_env_vars)
    env_vars.update(secrets)  # type: ignore[arg-type]
    if "AGENT_VERSION" not in env_vars:
        env_vars["AGENT_VERSION"] = get_project_version(find_project_root() or Path.cwd())
    env_vars.setdefault("NUM_WORKERS", str(num_workers))
    env_vars.setdefault("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "true")
    env_vars.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    return env_vars


def _get_resource_name_from_operation(operation_name: str) -> str:
    """Extract ReasoningEngine resource name from long-running operation name.

    GCP long-running operations on specific resources are guaranteed by API
    standards to end with "/operations/{operation_id}". Extract the full
    resource name by partitioning on "/operations/".
    """
    resource_name, _, _ = operation_name.rpartition("/operations/")
    return resource_name


def write_deployment_metadata(
    remote_agent: Any,
    cfg: ProjectConfig,
) -> None:
    """Write deployment metadata to file."""
    metadata = {
        "remote_agent_runtime_id": remote_agent.api_resource.name,
        "deployment_target": "agent_runtime",
        "is_a2a": cfg.is_a2a,
        "deployment_timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
    }

    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logging.info(f"Agent Runtime ID written to {METADATA_FILE}")


def print_deployment_success(
    remote_agent: Any,
    location: str,
    project: str,
    cfg: ProjectConfig,
) -> None:
    """Print deployment success message with console URL."""
    resource_name_parts = remote_agent.api_resource.name.split("/")
    agent_runtime_id = resource_name_parts[-1]
    project_number = resource_name_parts[1]

    if cfg.is_a2a:
        print(
            "\n✅ Deployment successful! Test your agent: notebooks/adk_a2a_app_testing.ipynb"
        )
        print(f"Agent Runtime ID: {remote_agent.api_resource.name}")
        agent_card_url = (
            f"https://{location}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{project}/locations/{location}/"
            f"reasoningEngines/{agent_runtime_id}/a2a/v1/card"
        )
        print(f"🪪 Agent Card URL: {agent_card_url}")
    else:
        print("\n✅ Deployment successful!")

    print(f"Agent Runtime ID: {remote_agent.api_resource.name}")

    service_account = remote_agent.api_resource.spec.service_account
    if service_account:
        print(f"Service Account: {service_account}")
    else:
        default_sa = (
            f"service-{project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
        )
        print(f"Service Account: {default_sa}")

    if not cfg.is_a2a:
        playground_url = (
            f"https://console.cloud.google.com/vertex-ai/agents/agent-engines/"
            f"locations/{location}/agent-engines/{agent_runtime_id}/"
            f"playground?project={project}"
        )
        print(f"\n📊 Open Console Playground: {playground_url}\n")
    else:
        console_url = (
            f"https://console.cloud.google.com/vertex-ai/agents/agent-engines/"
            f"locations/{location}/agent-engines/{agent_runtime_id}?project={project}"
        )
        print(f"\n📊 View in Console: {console_url}\n")


def setup_agent_identity(client: Any, project: str, display_name: str) -> Any:
    """Create agent with identity and grant required IAM roles."""
    click.echo(f"\n🔧 Creating agent identity for: {display_name}")
    agent = client.agent_engines.create(
        config={
            "identity_type": IdentityType.AGENT_IDENTITY,
            "display_name": display_name,
        }
    )

    roles = [
        "roles/aiplatform.user",
        "roles/serviceusage.serviceUsageConsumer",
        "roles/browser",
        "roles/cloudapiregistry.viewer",
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
    ]
    principal = f"principal://{agent.api_resource.spec.effective_identity}"
    click.echo(f"🔐 Granting IAM roles to: {principal}")
    proj_client = resourcemanager_v3.ProjectsClient()
    policy = proj_client.get_iam_policy(
        request=iam_policy_pb2.GetIamPolicyRequest(resource=f"projects/{project}")
    )
    for role in roles:
        policy.bindings.append(policy_pb2.Binding(role=role, members=[principal]))
    proj_client.set_iam_policy(
        request=iam_policy_pb2.SetIamPolicyRequest(
            resource=f"projects/{project}", policy=policy
        )
    )
    click.echo("  ✅ Agent identity ready")
    return agent


def _generate_requirements_file(requirements_path: str) -> None:
    """Auto-generate requirements.txt via uv export.

    Tries with --no-annotate first, falls back without it for older uv versions.
    Creates parent directories if they don't exist.
    """
    os.makedirs(os.path.dirname(requirements_path), exist_ok=True)

    project_root = find_project_root() or "."
    uv_lock_path = os.path.join(project_root, "uv.lock")
    if not os.path.exists(uv_lock_path):
        click.echo("  🔒 No uv.lock found. Running 'uv sync' to generate one...")
        try:
            run_resolved(
                ["uv", "sync"],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise click.ClickException(
                "Failed to run 'uv sync' to generate uv.lock"
            ) from e

    base_cmd = [
        "uv",
        "export",
        "--no-hashes",
        "--no-sources",
        "--no-header",
        "--no-dev",
        "--no-emit-project",
        "--locked",
    ]

    # Try with --no-annotate first (newer uv)
    result = run_resolved(
        [*base_cmd, "--no-annotate"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fall back without --no-annotate (older uv)
        result = run_resolved(
            base_cmd,
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to generate requirements file via 'uv export'.\n"
            f"  stderr: {result.stderr.strip()}\n"
            f"  Ensure 'uv' is installed and your project has a valid uv.lock.\n"
            f"  Alternatively, pass --requirements-file with a pre-built file."
        )

    with open(requirements_path, "w", encoding="utf-8") as f:
        f.write(result.stdout)

    click.echo(f"  📦 Auto-generated requirements: {requirements_path}")


def deploy_agent_runtime(
    *,
    cfg: ProjectConfig,
    project: str,
    location: str = "us-east1",
    display_name: str | None = None,
    description: str = "",
    source_packages: tuple[str, ...] | None = None,
    entrypoint_module: str | None = None,
    entrypoint_object: str = "agent_runtime",
    requirements_file: str | None = None,
    set_env_vars: str | None = None,
    set_secrets: str | None = None,
    labels: str | None = None,
    service_account: str | None = None,
    min_instances: int = 1,
    max_instances: int = 10,
    cpu: str = "4",
    memory: str = "8Gi",
    container_concurrency: int = 9,
    num_workers: int = 1,
    agent_identity: bool = False,
    no_wait: bool = False,
    psc_interface_config: dict | None = None,
) -> AgentEngine | None:
    """Deploy the agent to Vertex AI Agent Runtime.

    Args:
        cfg: Project configuration from pyproject.toml.
        project: GCP project ID. Defaults to ADC project.
        location: GCP region.
        display_name: Display name for the agent engine.
        description: Description of the agent.
        source_packages: Source packages to deploy.
        entrypoint_module: Python module path for the agent entrypoint.
        entrypoint_object: Name of the agent instance at module level.
        requirements_file: Path to requirements.txt file.
        set_env_vars: Comma-separated KEY=VALUE env vars.
        set_secrets: Comma-separated ENV_VAR=SECRET_ID pairs.
        labels: Comma-separated KEY=VALUE labels.
        service_account: Service account email.
        min_instances: Minimum number of instances.
        max_instances: Maximum number of instances.
        cpu: CPU limit.
        memory: Memory limit.
        container_concurrency: Container concurrency.
        num_workers: Number of worker processes.
        agent_identity: Enable agent identity.
        no_wait: If True, start the deployment and return immediately.
        psc_interface_config: PSC interface configuration dict for private
            VPC connectivity. Contains ``network_attachment`` and optionally
            ``dns_peering_configs``.

    Returns:
        The deployed AgentEngine instance, or None when no_wait is True.
    """
    if location == "global":
        raise click.ClickException(
            "Region 'global' is not supported for Agent Runtime deployments.\n"
            "  Please specify a regional location (e.g., 'us-central1', 'us-east1') via --region or in your project config."
        )

    agent_dir = cfg.agent_directory
    display_name = display_name or resolve_service_name(cfg)
    source_packages = source_packages or (f"./{agent_dir}",)
    entrypoint_module = entrypoint_module or f"{agent_dir}.agent_runtime_app"

    # Auto-generate requirements.txt if not explicitly provided
    requirements_file_explicit = requirements_file is not None
    requirements_file = requirements_file or f"{agent_dir}/app_utils/.requirements.txt"
    if not requirements_file_explicit:
        _generate_requirements_file(requirements_file)

    # Parse CLI environment variables, secrets, and labels
    secrets = parse_secrets(set_secrets)
    labels_dict = parse_key_value_pairs(labels)

    env_vars = _build_runtime_env_vars(
        set_env_vars=set_env_vars,
        secrets=secrets,
        num_workers=num_workers,
    )

    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🤖 DEPLOYING AGENT TO VERTEX AI AGENT ENGINE 🤖         ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # Log deployment parameters
    click.echo("\n📋 Deployment Parameters:")
    params = [
        ("Project", project),
        ("Location", location),
        ("Display Name", display_name),
        ("Min Instances", min_instances),
        ("Max Instances", max_instances),
        ("CPU", cpu),
        ("Memory", memory),
        ("Container Concurrency", container_concurrency),
    ]
    if service_account:
        params.append(("Service Account", service_account))
    if agent_identity:
        params.append(("Agent Identity", "Enabled (Preview)"))
    if psc_interface_config:
        params.append(
            ("Network Attachment", psc_interface_config.get("network_attachment", "—"))
        )
        for i, dc in enumerate(psc_interface_config.get("dns_peering_configs", [])):
            params.append(
                (
                    f"DNS Peering [{i}]",
                    f"{dc.get('domain', '')} → {dc.get('target_project', '')}/{dc.get('target_network', '')}",
                )
            )
    for name, value in params:
        click.echo(f"  {name}: {value}")
    if env_vars:
        click.echo("\n🌍 Environment Variables:")
        for key, value in sorted(env_vars.items()):
            click.echo(f"  {key}: {format_env_value(value)}")

    source_packages_list = list(source_packages)

    # Initialize vertexai client
    http_options = {"api_version": "v1beta1"} if agent_identity else None
    client = vertexai.Client(
        project=project,
        location=location,
        http_options=http_options,
    )
    vertexai.init(project=project, location=location)

    # Introspect agent via subprocess delegation — runs in the project's
    # own venv so the CLI doesn't need the project's dependencies.
    logging.info(f"Introspecting {entrypoint_module}.{entrypoint_object} via subprocess")
    class_methods_list = _introspect_agent_via_subprocess(
        entrypoint_module, entrypoint_object
    )

    config_kwargs: dict[str, Any] = {
        "display_name": display_name,
        "description": description,
        "source_packages": source_packages_list,
        "entrypoint_module": entrypoint_module,
        "entrypoint_object": entrypoint_object,
        "class_methods": class_methods_list,
        "env_vars": env_vars,
        "service_account": service_account,
        "requirements_file": requirements_file,
        "labels": labels_dict,
        "min_instances": min_instances,
        "max_instances": max_instances,
        "resource_limits": {"cpu": cpu, "memory": memory},
        "container_concurrency": container_concurrency,
        "identity_type": IdentityType.AGENT_IDENTITY if agent_identity else None,
    }

    # The Console uses agent_framework to decide which playground to render.
    # Set explicitly — the unset default does not map to "custom".
    config_kwargs["agent_framework"] = "custom" if cfg.is_a2a else "google-adk"

    if psc_interface_config is not None:
        config_kwargs["psc_interface_config"] = psc_interface_config

    config = AgentEngineConfig(**config_kwargs)

    # Check for existing agent
    existing_agents = list(client.agent_engines.list())
    matching_agents = [
        agent
        for agent in existing_agents
        if agent.api_resource.display_name == display_name
    ]

    # Setup agent identity on first deployment
    if agent_identity and not matching_agents:
        matching_agents = [setup_agent_identity(client, project, display_name)]

    # Deploy (create or update)
    action = "Updating" if matching_agents else "Creating"

    if no_wait:
        click.echo(f"\n🚀 {action} agent: {display_name} (returning immediately)...")
        operation = _start_deploy_operation(
            client,
            config,
            matching_agents,
            action="update" if matching_agents else "create",
        )
        write_operation(
            operation_name=operation.name,
            project=project,
            location=location,
            deployment_target="agent_runtime",
        )
        click.echo(f"\n📋 Operation started: {operation.name}")
        click.echo("   Check status with: agents-cli deploy --status")
        return None

    click.echo(f"\n🚀 {action} agent: {display_name} (this can take 5-10 minutes)...")

    operation = _start_deploy_operation(
        client,
        config,
        matching_agents,
        action="update" if matching_agents else "create",
    )
    write_operation(
        operation_name=operation.name,
        project=project,
        location=location,
        deployment_target="agent_runtime",
    )
    click.echo(f"   Operation: {operation.name}")
    click.echo(
        "   If this command is interrupted, run 'google-agents deploy --status' to check progress."
    )

    # Block until the operation completes
    _agent_engines_utils._await_operation(
        operation_name=operation.name,
        get_operation_fn=client.agent_engines._get_agent_operation,
    )

    # Build AgentEngine from completed operation
    completed_op = client.agent_engines._get_agent_operation(
        operation_name=operation.name,
    )
    if completed_op.error:
        clear_operation()
        raise click.ClickException(f"Deployment failed: {completed_op.error}")

    # Retrieve the newly created/updated agent engine using the public client.agent_engines.get()
    # to ensure all fields (including the api_resource name) are fully loaded and populated.
    resource_name = _get_resource_name_from_operation(operation.name)
    remote_agent = client.agent_engines.get(name=resource_name)

    # Clear secrets if explicitly set to empty
    if (
        set_secrets is not None
        and not secrets
        and matching_agents
        and remote_agent.api_resource
    ):
        clear_op = client.agent_engines._update(
            name=remote_agent.api_resource.name,
            config={
                "spec": {"deployment_spec": {"secret_env": []}},
                "update_mask": "spec.deployment_spec.secret_env",
            },
        )
        _agent_engines_utils._await_operation(
            operation_name=clear_op.name,
            get_operation_fn=client.agent_engines._get_agent_operation,
        )

    write_deployment_metadata(remote_agent, cfg)
    print_deployment_success(remote_agent, location, project, cfg)
    clear_operation()

    return remote_agent


def _start_deploy_operation(
    client: Any,
    config: AgentEngineConfig,
    matching_agents: list[Any],
    action: str,
) -> Any:
    """Start a create or update operation without waiting for completion.

    Replicates the first half of the public create()/update() methods —
    builds the API config and fires the request — but skips the blocking
    ``_await_operation()`` call.

    Returns:
        An ``AgentEngineOperation`` with ``.name`` and ``.done`` fields.
    """
    api_config = client.agent_engines._create_config(
        mode=action,
        display_name=config.display_name,
        description=config.description,
        source_packages=config.source_packages,
        entrypoint_module=config.entrypoint_module,
        entrypoint_object=config.entrypoint_object,
        class_methods=config.class_methods,
        env_vars=config.env_vars,
        service_account=config.service_account,
        requirements_file=config.requirements_file,
        labels=config.labels,
        min_instances=config.min_instances,
        max_instances=config.max_instances,
        resource_limits=config.resource_limits,
        container_concurrency=config.container_concurrency,
        identity_type=config.identity_type,
        agent_framework=config.agent_framework,
        psc_interface_config=config.psc_interface_config,
    )

    if matching_agents:
        return client.agent_engines._update(
            name=matching_agents[0].api_resource.name,
            config=api_config,
        )
    return client.agent_engines._create(config=api_config)


def check_agent_runtime_operation(
    cfg: ProjectConfig,
    project: str,
    location: str = "us-east1",
) -> None:
    """Check the status of a pending Agent Runtime deploy operation."""
    op_data = read_operation()
    if not op_data:
        raise click.ClickException(
            "No pending deployment operation found.\n"
            "  Run 'agents-cli deploy' or 'agents-cli deploy --no-wait' first."
        )

    operation_name = op_data["operation_name"]
    location = location if location != "us-east1" else op_data.get("location", location)
    started_at = op_data.get("started_at", "")

    client = vertexai.Client(project=project, location=location)
    operation = client.agent_engines._get_agent_operation(
        operation_name=operation_name,
    )

    if operation.done:
        if operation.error:
            clear_operation()
            raise click.ClickException(f"Deployment failed: {operation.error}")

        # Retrieve the newly created/updated agent engine using the public client.agent_engines.get()
        # to ensure all fields (including the api_resource name) are fully loaded and populated.
        resource_name = _get_resource_name_from_operation(operation_name)
        remote_agent = client.agent_engines.get(name=resource_name)

        write_deployment_metadata(remote_agent, cfg)
        print_deployment_success(remote_agent, location, project, cfg)
        clear_operation()
    else:
        elapsed = ""
        if started_at:
            start = datetime.datetime.fromisoformat(started_at)
            delta = datetime.datetime.now(tz=datetime.UTC) - start
            minutes = int(delta.total_seconds() // 60)
            seconds = int(delta.total_seconds() % 60)
            elapsed = f" ({minutes}m {seconds}s elapsed)"

        click.echo(f"⏳ Deployment still in progress{elapsed}")
        click.echo(f"   Operation: {operation_name}")
        click.echo("   Run 'agents-cli deploy --status' again to check.")
