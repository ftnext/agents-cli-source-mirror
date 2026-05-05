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

"""Upgrade command for upgrading existing projects to newer Agents CLI versions."""

import logging
import pathlib
import shutil
import subprocess
import tempfile

import click
from rich.console import Console
from rich.prompt import Prompt

from google.agents.cli._project import find_project_root

from ..utils.generation_metadata import metadata_to_cli_args
from ..utils.language import (
    get_language_config,
    update_acli_version,
)
from ..utils.merge import (
    apply_changes,
    display_results,
    run_create_command,
)
from ..utils.upgrade import (
    compare_all_files,
    group_results_by_action,
    merge_pyproject_dependencies,
    write_merged_dependencies,
)
from ..utils.version import get_current_version
from .enhance import get_project_acli_config

console = Console()


def _ensure_uvx_available() -> bool:
    """Check if uvx is available."""
    try:
        subprocess.run(["uvx", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _display_version_header(old_version: str, new_version: str) -> None:
    """Display the upgrade version header."""
    console.print()
    console.print(f"[bold blue]📦 Upgrading {old_version} → {new_version}[/bold blue]")
    console.print()


@click.command()
@click.argument(
    "project_path",
    type=click.Path(exists=True, path_type=pathlib.Path),
    default=".",
    required=False,
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview changes without applying them",
)
@click.option(
    "--auto-approve",
    "--yes",
    "-y",
    is_flag=True,
    help="Auto-apply non-conflicting changes without prompts",
)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    default=False,
    help="Enable interactive prompts for human use",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def upgrade(
    project_path: pathlib.Path,
    dry_run: bool,
    auto_approve: bool,
    interactive: bool,
    debug: bool,
) -> None:
    """Upgrade project to a newer agents-cli version.

    Applies a 3-way merge between the old template, the new template, and your
    project: unmodified files are auto-updated, your customizations are preserved,
    and conflicts are surfaced for manual resolution (with --interactive) or kept as-is.
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG, force=True)
        console.print("[dim]Debug mode enabled[/dim]")

    # Resolve project path
    project_dir = project_path.resolve()
    # Handle the case where we're in a subdirectory under the project root.
    project_root_dir = find_project_root(project_dir)
    if project_root_dir is not None:
        project_dir = project_root_dir
        console.print(f"[dim]Resolved project root to: {project_dir}[/dim]")

    metadata = get_project_acli_config(project_dir)
    if not metadata:
        console.print("[bold red]Error:[/bold red] No agents-cli metadata found.")
        console.print(
            "Ensure pyproject.toml has \\[tool.agents-cli] section "
            "or .acli.toml has \\[project] section."
        )
        raise SystemExit(1)

    # Get language from metadata for language-aware operations
    language = metadata.get("language", "python")

    # Version is normalized to acli_version by get_project_acli_config
    old_version = metadata.get("acli_version")
    if not old_version:
        console.print(
            "[bold red]Error:[/bold red] No acli_version found in project metadata."
        )
        lang_config = get_language_config(language)
        config_file = lang_config.get("config_file", "pyproject.toml")
        version_key = lang_config.get("version_key", "acli_version")
        console.print(
            f"The project metadata is missing the version. "
            f"Please ensure {config_file} has {version_key} set."
        )
        raise SystemExit(1)

    new_version = get_current_version()

    # Check if upgrade is needed
    if old_version == new_version:
        console.print(
            f"[bold green]✅[/bold green] Project is already at version {new_version}"
        )
        return

    # Check if uvx is available for re-templating old version
    if not _ensure_uvx_available():
        console.print(
            "[bold red]Error:[/bold red] 'uvx' is required for upgrade but not installed."
        )
        console.print(
            "[dim]Install uv to enable upgrade: curl -LsSf https://astral.sh/uv/install.sh | sh[/dim]"
        )
        raise SystemExit(1)

    _display_version_header(old_version, new_version)

    # Get project name and CLI args from metadata
    project_name = metadata.get("name", project_dir.name)
    agent_directory = metadata.get("agent_directory", "app")
    cli_args = metadata_to_cli_args(metadata)

    # Create temp directories for re-templating
    temp_base = pathlib.Path(tempfile.mkdtemp(prefix="acli_upgrade_"))
    old_template_dir = temp_base / "old"
    new_template_dir = temp_base / "new"

    try:
        console.print("[dim]Generating template versions for comparison...[/dim]")

        # Re-template old version
        console.print(f"[dim]  - Old template (v{old_version})...[/dim]")
        if not run_create_command(cli_args, old_template_dir, project_name, old_version):
            console.print(
                f"[bold red]Error:[/bold red] Failed to generate old template (v{old_version})"
            )
            console.print(
                "[dim]This version may not be available. Try upgrading from a more recent version.[/dim]"
            )
            raise SystemExit(1)

        # Re-template new version
        console.print(f"[dim]  - New template (v{new_version})...[/dim]")
        if not run_create_command(cli_args, new_template_dir, project_name):
            console.print(
                f"[bold red]Error:[/bold red] Failed to generate new template (v{new_version})"
            )
            raise SystemExit(1)

        # The templates are created in subdirectories named after the project
        old_template_project = old_template_dir / project_name
        new_template_project = new_template_dir / project_name

        console.print()

        # Compare all files
        console.print("[dim]Comparing files...[/dim]")
        results = compare_all_files(
            project_dir,
            old_template_project,
            new_template_project,
            agent_directory,
        )

        # Group by action
        groups = group_results_by_action(results)

        # Handle dependency merging (only for languages that strip dependencies)
        lang_config = get_language_config(language)
        dep_result = None
        if lang_config.get("strip_dependencies", True):
            dep_result = merge_pyproject_dependencies(
                project_dir / "pyproject.toml",
                old_template_project / "pyproject.toml",
                new_template_project / "pyproject.toml",
            )

        console.print()

        # Display results
        display_results(groups, dep_result.changes if dep_result else [], dry_run)

        # Check if there's anything to do
        total_changes = (
            len(groups["auto_update"])
            + len(groups["new"])
            + len(groups["removed"])
            + len(groups["conflict"])
        )

        has_dep_changes = dep_result and dep_result.changes
        if total_changes == 0 and not has_dep_changes:
            console.print("[bold green]✅[/bold green] No changes needed!")
            return

        # Confirm before applying (only in interactive mode)
        if interactive and not dry_run:
            prompt_text = "\nProceed with upgrade?"
            if groups["conflict"]:
                prompt_text = "\nProceed? (you'll resolve conflicts next)"
            proceed = Prompt.ask(
                prompt_text,
                choices=["y", "n"],
                case_sensitive=False,
                default="y",
            ).lower()
            if proceed != "y":
                console.print("[yellow]Upgrade cancelled.[/yellow]")
                return

        # Apply changes
        counts = apply_changes(
            groups,
            project_dir,
            new_template_project,
            auto_approve,
            dry_run,
            interactive=interactive,
        )

        # Apply dependency changes (Python only)
        if not dry_run and dep_result and dep_result.changes:
            write_merged_dependencies(
                project_dir / "pyproject.toml",
                dep_result.merged_deps,
            )

        # Update metadata version using language-aware utility
        if not dry_run:
            update_acli_version(project_dir, language, new_version)

        # Summary
        console.print()
        if dry_run:
            console.print(
                "[bold yellow]Dry run complete.[/bold yellow] "
                "Run without --dry-run to apply changes."
            )
        else:
            console.print(f"  Updated: {counts['updated']} files")
            console.print(f"  Added: {counts['added']} files")
            console.print(f"  Removed: {counts['removed']} files")
            if counts["conflicts_kept"] or counts["conflicts_updated"]:
                console.print(
                    f"  Conflicts: {counts['conflicts_updated']} updated, "
                    f"{counts['conflicts_kept']} kept yours"
                )
            console.print()
            console.print("[bold green]✅ Upgrade complete![/bold green]")

    finally:
        # Cleanup temp directories
        shutil.rmtree(temp_base, ignore_errors=True)
