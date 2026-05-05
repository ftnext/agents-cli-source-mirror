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

"""agents-cli deploy command — deploy the agent."""

import subprocess
import sys

import click

from google.agents.cli._project import (
    ProjectConfig,
    chdir_project_root,
    check_cli_version,
    read_project_config,
    require_deployment_target,
    require_tool,
)
from google.agents.cli._runner import run
from google.agents.cli.deploy._utils import parse_key_value_pairs


def deploy_agent_runtime(*args, **kwargs):
    """Lazy-loading wrapper for deploy_agent_runtime.

    The underlying module imports heavy Google Cloud and Vertex AI SDKs.
    We defer the import until execution to keep the CLI's startup fast,
    while keeping this wrapper at the module level to support unit test patching.
    """
    from google.agents.cli.deploy.agent_runtime import (
        deploy_agent_runtime as _deploy_agent_runtime,
    )

    return _deploy_agent_runtime(*args, **kwargs)


def check_agent_runtime_operation(*args, **kwargs):
    """Lazy-loading wrapper for check_agent_runtime_operation.

    The underlying module imports heavy Google Cloud and Vertex AI SDKs.
    We defer the import until execution to keep the CLI's startup fast,
    while keeping this wrapper at the module level to support unit test patching.
    """
    from google.agents.cli.deploy.agent_runtime import (
        check_agent_runtime_operation as _check_agent_runtime_operation,
    )

    return _check_agent_runtime_operation(*args, **kwargs)


@click.command("deploy", context_settings={"ignore_unknown_options": True})
@click.option("--project", default=None, help="GCP project ID.")
@click.option("--region", default=None, help="GCP region.")
@click.option("--secrets", default=None, help="Comma-separated ENV=SECRET pairs.")
@click.option(
    "--agent-identity", is_flag=True, default=False, help="Enable agent identity."
)
@click.option(
    "--update-env-vars", default=None, help="Comma-separated KEY=VALUE env vars."
)
@click.option(
    "--iap",
    is_flag=True,
    default=False,
    help="Enable Identity-Aware Proxy (Cloud Run).",
)
@click.option("--port", default=None, type=int, help="Container port (Cloud Run).")
@click.option("--memory", default="4Gi", help="Memory limit (Cloud Run). Default: 4Gi.")
@click.option("--service-account", default=None, help="Service account email.")
@click.option(
    "--image",
    default=None,
    help="Container image URI (Cloud Run / GKE). Skips source build.",
)
@click.option(
    "--cluster-name",
    default=None,
    help="Cluster name (GKE).",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    default=False,
    help="Print what would be executed without running it.",
)
@click.option(
    "--list",
    "list_deployments",
    is_flag=True,
    default=False,
    help="List existing deployments and exit.",
)
@click.option(
    "--no-wait",
    "no_wait",
    is_flag=True,
    default=False,
    help="Start the deployment and return immediately.",
)
@click.option(
    "--status",
    "status",
    is_flag=True,
    default=False,
    help="Check the status of a pending --no-wait deployment.",
)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    default=False,
    help="Enable interactive prompts for underlying tooling (gcloud, etc).",
)
@click.option(
    "--no-confirm-project",
    is_flag=True,
    default=False,
    help="Skip project confirmation prompt.",
)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
def cmd_deploy(
    project,
    region,
    secrets,
    agent_identity,
    update_env_vars,
    iap,
    port,
    memory,
    service_account,
    image,
    cluster_name,
    dry_run,
    list_deployments,
    no_wait,
    status,
    interactive,
    no_confirm_project,
    extra_args,
):
    """Deploy the agent.

    \b
    Dispatches by deployment target configured in pyproject.toml:
      agent_runtime → Agent Runtime deployment
      cloud_run    → gcloud beta run deploy
      gke          → terraform + docker build + kubectl apply

    \b
    Cloud Run accepts extra arguments, forwarded to gcloud run deploy.
    Run 'gcloud run deploy --help' for all available options.

    \b
    Use --list to show existing deployments:
      agents-cli deploy --list

    \b
    Use --no-wait to start a deployment and return immediately:
      agents-cli deploy --no-wait

    \b
    Use --status to check on a --no-wait deployment:
      agents-cli deploy --status
    """
    chdir_project_root()
    cfg = read_project_config()
    check_cli_version(cfg)
    require_deployment_target(cfg)
    region = region or cfg.region

    project_explicitly_passed = bool(project)

    # Resolve project once upfront — all deployment targets need it
    if not project_explicitly_passed:
        project = _try_resolve_gcp_project()
    if not project:
        raise click.ClickException(
            "Could not determine GCP project.\n"
            "  Pass --project <PROJECT_ID> or set a default:\n"
            "    gcloud config set project <PROJECT_ID>"
        )

    if status:
        _check_deploy_status(cfg, project, region)
        return

    if list_deployments:
        _list_deployments(cfg, project, region)
        return

    # Prompt for confirmation if project was resolved automatically and not skipping
    confirm_project = not project_explicitly_passed and not no_confirm_project
    if confirm_project:
        if not interactive:
            raise click.ClickException(
                f"About to deploy to Google Cloud project '{project}' (resolved from `gcloud config`) — confirmation required.\n"
                "  To proceed, either:\n"
                f"    • Pass it explicitly:    --project {project}\n"
                "    • Skip the prompt:       --no-confirm-project\n"
                "    • Run interactively:     -i"
            )
        if not click.confirm(
            f"Deploying to Google Cloud project '{project}'. Proceed?", default=True
        ):
            raise click.ClickException("Aborted by user.")

    if cfg.deployment_target == "agent_runtime":
        if dry_run:
            click.echo(
                f"  Would deploy to Agent Runtime: project={project}, region={region}"
            )
            return
        deploy_agent_runtime(
            cfg=cfg,
            project=project,
            location=region,
            set_env_vars=update_env_vars,
            set_secrets=secrets,
            service_account=service_account,
            agent_identity=agent_identity,
            no_wait=no_wait,
        )

    elif cfg.deployment_target == "cloud_run":
        require_tool(
            "gcloud",
            "Install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install",
        )
        service_name = cfg.project_name or "agent"

        # Build set of CLI-managed args for conflict detection
        managed_args = {
            "--source",
            "--image",
            "--project",
            "--memory",
            "--update-env-vars",
        }
        if region:
            managed_args.add("--region")
        if port:
            managed_args.add("--port")
        if service_account:
            managed_args.add("--service-account")

        _validate_gcloud_extra_args(extra_args, managed_args)

        args = ["gcloud", "beta", "run", "deploy", service_name]
        if project:
            args.extend(["--project", project])
        if region:
            args.extend(["--region", region])
        if image:
            args.extend(["--image", image])
        else:
            args.extend(["--source", "."])
        args.extend(["--memory", memory])
        args.append("--no-allow-unauthenticated")
        args.append("--no-cpu-throttling")
        if port:
            args.extend(["--port", str(port)])
        if iap:
            args.append("--iap")
        if service_account:
            args.extend(["--service-account", service_account])

        # Inject environment variables (AGENT_VERSION auto-set, user can override)
        env_var_map = parse_key_value_pairs(update_env_vars)
        env_var_map.setdefault("AGENT_VERSION", cfg.version)

        # Set APP_URL so the service knows its own URL (used by A2A agent cards, etc.)
        if "APP_URL" not in env_var_map and project:
            try:
                result = subprocess.run(
                    [
                        "gcloud",
                        "projects",
                        "describe",
                        project,
                        "--format=value(projectNumber)",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                project_number = result.stdout.strip()
                env_var_map["APP_URL"] = (
                    f"https://{service_name}-{project_number}.{region}.run.app"
                )
            except (subprocess.CalledProcessError, OSError):
                click.echo(
                    "  ⚠️  Could not determine project number — skipping APP_URL injection."
                )
        env_var_str = ",".join(f"{k}={v}" for k, v in env_var_map.items())
        args.extend(["--update-env-vars", env_var_str])

        # Merge labels: combine user --labels= with created-by=adk
        user_labels, remaining_args = _extract_labels(extra_args)
        all_labels = ["created-by=adk", *user_labels]
        args.extend(["--labels", ",".join(all_labels)])

        # Passthrough remaining args
        args.extend(remaining_args)

        if no_wait:
            args.append("--async")

        if dry_run:
            click.echo(f"  Would run: {' '.join(str(a) for a in args)}")
            return

        # Stream stdout and stderr to terminal in real time, capturing stderr for error detection
        cmd_str = " ".join(str(a) for a in args)
        click.secho(f"  ▸ {cmd_str}", fg="cyan", dim=True)

        process = subprocess.Popen(
            args, stdout=sys.stdout, stderr=subprocess.PIPE, text=True
        )

        assert process.stderr is not None
        stderr_chars = []
        while True:
            char = process.stderr.read(1)
            if not char:
                break
            sys.stderr.write(char)
            sys.stderr.flush()
            stderr_chars.append(char)

        process.wait()

        if process.returncode != 0:
            stderr = "".join(stderr_chars)
            if "SERVICE_DISABLED" in stderr:
                raise click.ClickException(
                    "Cloud Run or Cloud Build API is not enabled.\n"
                    "Please enable them by running:\n"
                    f"  gcloud services enable cloudbuild.googleapis.com run.googleapis.com --project={project}"
                )
            else:
                raise click.ClickException(
                    f"Cloud Run deployment failed (exit code {process.returncode})"
                )

    elif cfg.deployment_target == "gke":
        if no_wait:
            raise click.ClickException("--no-wait is not supported for GKE deployments.")
        _deploy_gke(cfg, project, region, image, cluster_name, dry_run)

    else:
        raise click.ClickException(
            f"Unknown deployment target: {cfg.deployment_target}. "
            "Set [tool.agents-cli] deployment_target in pyproject.toml."
        )


def _validate_gcloud_extra_args(extra_args, managed_args):
    """Reject extra args that conflict with CLI-managed args."""
    if not extra_args:
        return
    user_arg_names = {arg.split("=")[0] for arg in extra_args if arg.startswith("--")}
    conflicts = user_arg_names.intersection(managed_args)
    if conflicts:
        conflict_list = ", ".join(f"'{a}'" for a in sorted(conflicts))
        raise click.ClickException(
            f"The argument(s) {conflict_list} conflict with automatic configuration. "
            "These are set automatically — remove them from your command."
        )


def _extract_labels(extra_args):
    """Separate --labels= from other args, return (label_values, remaining_args)."""
    labels, remaining = [], []
    for arg in extra_args:
        if arg.startswith("--labels="):
            labels.append(arg[len("--labels=") :])
        else:
            remaining.append(arg)
    return labels, remaining


def _enable_cloud_run_apis(project: str | None) -> None:
    """Enable Cloud Build and Cloud Run APIs, then retry the deployment."""
    click.echo("Enabling required APIs (Cloud Build, Cloud Run)...")
    enable_base = ["gcloud", "services", "enable"]
    if project:
        enable_base.extend(["--project", project])
    for api in ("cloudbuild.googleapis.com", "run.googleapis.com"):
        run([*enable_base, api], capture=True, print_cmd=False, check=False)


def _check_deploy_status(cfg: ProjectConfig, project: str, region: str) -> None:
    """Check the status of a pending --no-wait deployment."""
    if cfg.deployment_target == "agent_runtime":
        check_agent_runtime_operation(
            cfg=cfg,
            project=project,
            location=region,
        )
    elif cfg.deployment_target == "cloud_run":
        _check_cloud_run_status(cfg, project, region)
    elif cfg.deployment_target == "gke":
        raise click.ClickException("--status is not supported for GKE deployments.")
    else:
        raise click.ClickException(f"Unknown deployment target: {cfg.deployment_target}")


def _check_cloud_run_status(cfg: ProjectConfig, project: str | None, region: str) -> None:
    """Check the status of the Cloud Run service."""
    require_tool(
        "gcloud",
        "Install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install",
    )
    service_name = cfg.project_name or "agent"
    args = [
        "gcloud",
        "run",
        "services",
        "describe",
        service_name,
        "--format=json",
    ]
    if project:
        args.extend(["--project", project])
    if region:
        args.extend(["--region", region])

    result = run(args, capture=True, print_cmd=False, check=False)
    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to describe Cloud Run service '{service_name}'.\n"
            "  The service may not exist yet or the deployment may have failed."
        )

    import json

    svc = json.loads(result.stdout)
    conditions = svc.get("status", {}).get("conditions", [])
    ready = any(
        c.get("type") == "Ready" and c.get("status") == "True" for c in conditions
    )

    if ready:
        url = svc.get("status", {}).get("url", "")
        click.echo(f"✅ Cloud Run service '{service_name}' is ready.")
        if url:
            click.echo(f"   URL: {url}")
    else:
        reason = ""
        for c in conditions:
            if c.get("type") == "Ready":
                reason = c.get("message", "")
                break
        click.echo(f"⏳ Cloud Run service '{service_name}' is not yet ready.")
        if reason:
            click.echo(f"   Reason: {reason}")


def _try_resolve_gcp_project() -> str | None:
    """Try to resolve GCP project from gcloud default config.

    Returns the project ID if found, or None with a warning if not.
    """
    result = run(
        ["gcloud", "config", "get-value", "project"],
        capture=True,
        print_cmd=False,
        check=False,
    )
    resolved = result.stdout.strip() if result.returncode == 0 else ""
    if resolved and resolved != "(unset)":
        return resolved

    return None


def _deploy_gke(cfg, project, region, image, cluster_name, dry_run):
    """GKE deployment: single linear flow with conditional steps.

    When ``image`` is provided (CI/CD mode), skips terraform and docker build.
    When ``image`` is None (local dev mode), runs targeted terraform + build flow.
    Both paths share cluster credentials, kubectl rollout, APP_URL injection,
    and external IP steps.
    """
    deploy_targets = [
        "google_container_cluster.app",
        "google_artifact_registry_repository.docker_repo",
        "google_compute_router_nat.nat",
        "google_compute_firewall.allow_internal",
        "google_service_account.app_sa",
        "google_project_iam_member.app_sa_roles",
        "google_project_iam_member.default_compute_sa_storage_object_creator",
        "google_service_account_iam_member.workload_identity_binding",
        "kubernetes_namespace_v1.app",
        "kubernetes_service_account_v1.app",
        "kubernetes_deployment_v1.app",
        "kubernetes_service_v1.app",
        "kubernetes_horizontal_pod_autoscaler_v2.app",
        "kubernetes_pod_disruption_budget_v1.app",
    ]
    require_tool(
        "gcloud",
        "Install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install",
    )
    require_tool("kubectl", "Install kubectl: https://kubernetes.io/docs/tasks/tools/")
    service_name = cfg.project_name or "agent"
    cluster_name = cluster_name or service_name

    if not image:
        require_tool(
            "terraform",
            "Install Terraform: https://developer.hashicorp.com/terraform/install",
        )

    if dry_run:
        if not image:
            tf_dir = "deployment/terraform/single-project"
            click.echo(f"  Would run: terraform -chdir={tf_dir} init")
            click.echo(
                f"  Would run: terraform -chdir={tf_dir} apply -auto-approve"
                f" -target=({len(deploy_targets)} targets)"
            )
            click.echo("  Would run: gcloud builds submit --tag ...")
        click.echo("  Would run: gcloud container clusters get-credentials ...")
        click.echo(
            f"  Would run: kubectl set image ... {image or f'{region}-docker.pkg.dev/{project}/{service_name}/{service_name}:latest'}"
        )
        click.echo("  Would run: kubectl get svc ... (service IP)")
        click.echo("  Would run: kubectl set env ... APP_URL=...")
        click.echo("  Would run: kubectl rollout status ...")
        return

    # Step 1: Targeted Terraform (local dev only)
    if not image:
        tf_dir = "deployment/terraform/single-project"
        click.echo("\n🏗️  Provisioning infrastructure with Terraform...")
        run(
            ["terraform", f"-chdir={tf_dir}", "init"],
            check_err_msg="Terraform init failed",
        )
        apply_args = [
            "terraform",
            f"-chdir={tf_dir}",
            "apply",
            "-auto-approve",
            f"-var=project_id={project}",
        ]
        for target in deploy_targets:
            apply_args.extend(["-target", target])
        run(apply_args, check_err_msg="Terraform apply failed")

    # Step 2: Get cluster credentials
    click.echo("\n🔑 Getting cluster credentials...")
    run(
        [
            "gcloud",
            "container",
            "clusters",
            "get-credentials",
            cluster_name,
            "--region",
            region,
            *(["--project", project] if project else []),
        ],
        check_err_msg="Failed to get cluster credentials",
    )

    # Step 3: Build and push container image (local dev only)
    if not image:
        image = f"{region}-docker.pkg.dev/{project}/{service_name}/{service_name}:latest"
        click.echo(f"\n🐳 Building container image: {image}")
        run(
            ["gcloud", "builds", "submit", "--tag", image, "--project", project],
            check_err_msg="Container build failed",
        )

    # Step 4: Update container image
    click.echo("\n🔄 Rolling out deployment...")
    run(
        [
            "kubectl",
            "set",
            "image",
            f"deployment/{service_name}",
            f"{service_name}={image}",
            "-n",
            service_name,
        ],
        check_err_msg="kubectl set image failed",
    )

    # Step 5: Set APP_URL from LoadBalancer IP (used by A2A agents for agent card URL)
    click.echo("\n🌐 Getting service IP...")
    ip_result = run(
        [
            "kubectl",
            "get",
            "service",
            service_name,
            "-n",
            service_name,
            "-o",
            "jsonpath={.status.loadBalancer.ingress[0].ip}",
        ],
        capture=True,
        print_cmd=False,
        check=False,
    )
    service_ip = ip_result.stdout.strip() if ip_result.returncode == 0 else ""
    if service_ip:
        app_url = f"http://{service_ip}:8080"
        click.echo(f"  Service IP: {service_ip}")
        run(
            [
                "kubectl",
                "set",
                "env",
                f"deployment/{service_name}",
                f"APP_URL={app_url}",
                "-n",
                service_name,
            ],
            check_err_msg="Failed to set APP_URL",
        )
    else:
        click.echo("  ⚠️  Could not determine service IP — skipping APP_URL injection.")

    # Step 6: Wait for rollout
    run(
        [
            "kubectl",
            "rollout",
            "status",
            f"deployment/{service_name}",
            "-n",
            service_name,
            "--timeout=600s",
        ],
        check_err_msg="Rollout failed",
    )

    # Step 7: Print summary
    click.echo("\n\n✅ GKE deployment complete!")
    if service_ip:
        click.echo(f"   Internal service IP: {service_ip}")
    click.echo(
        f"   For local access: kubectl port-forward svc/{service_name} 8080:8080 -n {service_name}"
    )


def _list_deployments(cfg: ProjectConfig, project: str | None, region: str) -> None:
    """List existing deployments for the current project's deployment target."""
    if cfg.deployment_target == "agent_runtime":
        _list_agent_runtime_deployments(project, region)
    elif cfg.deployment_target == "cloud_run":
        _list_cloud_run_deployments(project, region)
    elif cfg.deployment_target == "gke":
        _list_gke_deployments()
    else:
        raise click.ClickException(f"Unknown deployment target: {cfg.deployment_target}")


def _list_agent_runtime_deployments(project: str | None, location: str) -> None:
    """List Agent Runtime deployments via the Vertex AI SDK."""
    import warnings

    import google.auth
    import vertexai

    warnings.filterwarnings(
        "ignore", category=FutureWarning, module="google.cloud.aiplatform"
    )

    if not project:
        _, project = google.auth.default()
    if not project:
        raise click.ClickException(
            "Could not determine GCP project. Pass --project or set a default project."
        )

    client = vertexai.Client(project=project, location=location)
    agents = list(client.agent_engines.list())

    if not agents:
        click.echo(f"No Agent Runtime deployments found in {project} ({location}).")
        return

    from rich.console import Console
    from rich.table import Table

    table = Table(title=f"Agent Runtime Deployments — {project} ({location})")
    table.add_column("Display Name", style="bold")
    table.add_column("Resource Name", style="dim")
    table.add_column("Create Time")

    for agent in agents:
        res = agent.api_resource
        display_name = getattr(res, "display_name", None) or "—"
        name = getattr(res, "name", None) or "—"
        create_time = getattr(res, "create_time", None)
        time_str = create_time.strftime("%Y-%m-%d %H:%M") if create_time else "—"
        table.add_row(display_name, name, time_str)

    console = Console()
    console.print()
    console.print(table)


def _list_cloud_run_deployments(project: str | None, region: str | None) -> None:
    """List Cloud Run services via gcloud."""
    require_tool(
        "gcloud",
        "Install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install",
    )

    args = [
        "gcloud",
        "run",
        "services",
        "list",
        "--format=json",
    ]
    if project:
        args.extend(["--project", project])
    if region:
        args.extend(["--region", region])

    result = run(args, capture=True, print_cmd=False, check=False)
    if result.returncode != 0:
        raise click.ClickException("Failed to list Cloud Run services.")

    import json

    services = json.loads(result.stdout) if result.stdout.strip() else []

    if not services:
        location_label = f" in {region}" if region else ""
        project_label = f" ({project})" if project else ""
        click.echo(f"No Cloud Run services found{location_label}{project_label}.")
        return

    from rich.console import Console
    from rich.table import Table

    title_parts = ["Cloud Run Services"]
    if project:
        title_parts.append(f"— {project}")
    if region:
        title_parts.append(f"({region})")
    table = Table(title=" ".join(title_parts))
    table.add_column("Service Name", style="bold")
    table.add_column("Region")
    table.add_column("URL", style="dim")
    table.add_column("Last Deployed")

    for svc in services:
        metadata = svc.get("metadata", {})
        status = svc.get("status", {})
        name = metadata.get("name", "—")
        labels = metadata.get("labels", {})
        svc_region = labels.get("cloud.googleapis.com/location", "—")
        url = status.get("url", "—")
        # Cloud Run uses metadata.creationTimestamp or status conditions
        conditions = status.get("conditions", [])
        ready_time = "—"
        for cond in conditions:
            if cond.get("type") == "Ready" and cond.get("lastTransitionTime"):
                ready_time = cond["lastTransitionTime"][:16].replace("T", " ")
                break
        table.add_row(name, svc_region, url, ready_time)

    console = Console()
    console.print()
    console.print(table)


def _list_gke_deployments() -> None:
    """List GKE deployments via kubectl."""
    require_tool("kubectl", "Install kubectl: https://kubernetes.io/docs/tasks/tools/")

    result = run(
        ["kubectl", "get", "deployments", "-o", "json"],
        capture=True,
        print_cmd=False,
        check=False,
    )
    if result.returncode != 0:
        raise click.ClickException(
            "Failed to list GKE deployments.\n"
            "  Ensure kubectl is configured with cluster credentials."
        )

    import json

    data = json.loads(result.stdout) if result.stdout.strip() else {}
    items = data.get("items", [])

    if not items:
        click.echo("No GKE deployments found in the current cluster.")
        return

    from rich.console import Console
    from rich.table import Table

    table = Table(title="GKE Deployments")
    table.add_column("Name", style="bold")
    table.add_column("Ready")
    table.add_column("Namespace")
    table.add_column("Created")

    for dep in items:
        metadata = dep.get("metadata", {})
        status = dep.get("status", {})
        name = metadata.get("name", "—")
        namespace = metadata.get("namespace", "—")
        ready = f"{status.get('readyReplicas', 0)}/{status.get('replicas', 0)}"
        created = metadata.get("creationTimestamp", "—")[:16].replace("T", " ")
        table.add_row(name, ready, namespace, created)

    console = Console()
    console.print()
    console.print(table)
