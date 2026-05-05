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

"""agents-cli setup command — install skills via npx skills CLI."""

import random
import subprocess
from pathlib import Path

import click

from google.agents.cli._project import get_npx_path
from google.agents.cli._runner import run
from google.agents.cli._skills_check import SKILLS_NPX_PACKAGE

_MOTTOS = [
    "Give your coding agent the power to build ADK projects.",
    "From prototype to production — one CLI away.",
    "Skills up. Ship faster.",
    "Agents skills, installed in seconds.",
    "Your coding agent just got an upgrade.",
]

_DEFAULT_SKILLS_SOURCE = "https://github.com/google/agents-cli"


def _print_logo():
    """Print the AGENTS CLI ASCII art logo with a random motto."""
    click.secho(
        " █▀█ █▀▀ █▀▀ █▄ █ ▀█▀ █▀   █▀▀ █  █",
        fg="blue",
        bold=True,
    )
    click.secho(
        " █▀█ █▄█ ██▄ █ ▀█  █  ▄█   █▄▄ █▄ █",
        fg="cyan",
        bold=True,
    )
    click.echo()
    click.echo(f" {random.choice(_MOTTOS)}")


def _print_section(number, title):
    """Print a numbered section header."""
    click.echo()
    click.secho(f" {number}. {title}", bold=True)
    click.echo(f" {'─' * (len(title) + 3)}")


def _get_source_root():
    """Return the cwd if it is the agents-cli repo root, else None.

    Checks that a ``pyproject.toml`` with the ``agents-cli`` package
    name exists in the current working directory.
    """
    candidate = Path.cwd() / "pyproject.toml"
    if candidate.is_file():
        try:
            text = candidate.read_text()
            if 'name = "google-agents-cli"' in text:
                return Path.cwd()
        except OSError:
            pass
    return None


def _run_npx_skills(args, spinner_msg):
    """Run an npx skills command, streaming output in real-time.

    Streams stdout/stderr line-by-line, filtering npm/npx boilerplate.
    All non-noise lines are printed immediately. Only concise summary
    lines (e.g. "Installed 6 skills", "Found 6 skills") are collected
    for the end summary.

    Returns:
        A list of summary-worthy lines (short, no decorative content).

    Raises:
        click.ClickException: If the npx process exits non-zero.
    """
    cmd_str = " ".join(args)
    click.secho(f"  \u25b8 {cmd_str}", fg="cyan", dim=True)

    summary_lines = []
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # Read stdout line-by-line
    assert proc.stdout is not None
    for line in proc.stdout:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip npx download/cache noise
        if stripped.startswith("npm ") or stripped.startswith("npx:"):
            continue
        # Skip ASCII art banners (block characters)
        if any(ch in stripped for ch in "█╗╔║╚╝"):
            continue
        # Strip leading box-drawing / bullet prefixes to extract text
        clean = stripped.lstrip("┌┐└┘├┤│◇●◆✓─╮╯ ")
        if not clean:
            continue
        # Skip per-agent detail lines
        if clean.startswith(("universal:", "symlink", "overwrites:")):
            continue
        # Skip purely decorative headers (e.g. "Installation Summary ────")
        if "──" in clean:
            continue
        click.echo(f"  {clean}")
        # Collect concise summary-worthy lines for the recap
        if len(clean) < 80 and clean.startswith(
            ("Installed", "Found", "Done", "Removed", "Updated")
        ):
            summary_lines.append(clean)

    proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ""
        click.secho("  Error running npx skills:", fg="red")
        if stderr.strip():
            for line in stderr.strip().splitlines():
                click.echo(f"  {line}")
        raise click.ClickException("npx skills failed")

    return summary_lines


@click.command("setup")
@click.option(
    "--workspace",
    is_flag=True,
    default=False,
    help=(
        "Install to project/workspace scope instead of global. "
        "Skills are installed relative to the current directory."
    ),
)
@click.option(
    "--skip-auth",
    is_flag=True,
    default=False,
    help="Skip the authentication step.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without making changes.",
)
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Install as editable from the local repo (for contributors).",
)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    default=False,
    help="Enable interactive authentication prompt if not already authenticated.",
)
@click.option(
    "--skills-source",
    default=None,
    help="Skills source: local path, GitHub owner/repo, or URL. Overrides the bundled skills.",
)
def cmd_setup(workspace, skip_auth, dry_run, dev, interactive, skills_source):
    """Install agents-cli and skills to detected coding agents.

    Installs the agents-cli tool (via uv tool install) and detects
    installed coding agents (Claude Code, Gemini CLI, Cursor,
    Windsurf, etc.) to install ADK development skills via npx skills.

    By default, skills are installed globally.
    Use --workspace to install at the project level instead.
    Use --dry-run to preview what would happen without executing.
    Use --dev to install agents-cli as editable from the local repo (for contributors).
    Use --interactive / -i to enable interactive authentication if not already logged in.
    """
    click.echo()
    _print_logo()

    scope = "workspace" if workspace else "global"

    source = _DEFAULT_SKILLS_SOURCE
    if dev and not skills_source:
        # In dev mode, use skills from the local repo checkout
        source = str(Path.cwd() / "skills")
    elif skills_source:
        source_path = Path(skills_source)
        # Only resolve to an absolute path if the source is a local file/directory
        # to prevent resolving remote URIs (e.g., GitHub URLs or package identifiers).
        if skills_source.startswith((".", "/")) or source_path.exists():
            source = str(source_path.resolve())
        else:
            source = skills_source
    args = [get_npx_path(), "-y", SKILLS_NPX_PACKAGE, "add", source, "-y", "--all"]
    if not workspace:
        args.append("-g")

    # ── Dry Run ──
    if dry_run:
        _print_section(1, "Dry Run")
        click.echo()
        if dev:
            project_root = _get_source_root()
            if not project_root:
                raise click.ClickException(
                    "--dev requires running from the root of the agents-cli repository"
                )
            click.echo("  Would install agents-cli (editable):")
            click.secho(
                f"  \u25b8 uv tool install --force --editable {project_root}",
                fg="cyan",
                dim=True,
            )
        else:
            click.echo("  Would install agents-cli:")
            click.secho(
                "  \u25b8 uv tool install google-agents-cli",
                fg="cyan",
                dim=True,
            )
        click.echo()
        click.echo("  Would install skills:")
        click.secho(f"  \u25b8 {' '.join(args)}", fg="cyan", dim=True)
        click.echo(f"  Scope: {scope}")
        click.echo()

        if not skip_auth:
            from google.agents.cli.auth import is_authenticated

            authed, display = is_authenticated()
            if authed:
                click.echo(f"  Auth:  {display}")
            else:
                click.echo("  Auth:  Not authenticated")
        else:
            click.echo("  Auth:  Skipped")

        click.echo()
        click.secho("  No changes made (dry run).", fg="yellow")
        click.echo()
        return

    step = 1

    # ── Authentication ──
    _print_section(step, "Authentication")
    step += 1
    if not skip_auth:
        from google.agents.cli.auth import is_authenticated, run_auth_step

        authed, display = is_authenticated()
        if authed:
            click.echo()
            click.secho(f"  Authenticated as {display}", fg="green")
        elif interactive:
            run_auth_step(show_header=False)
        else:
            click.echo()
            click.secho(
                "  Not authenticated. Run with --interactive (-i) to authenticate interactively.",
                fg="yellow",
                dim=True,
            )
    else:
        click.echo()
        click.secho("  Skipped (--skip-auth)", dim=True)

    # ── CLI Installation ──
    _print_section(step, "CLI Installation")
    step += 1
    click.echo()
    cli_installed = False
    if dev:
        project_root = _get_source_root()
        if not project_root:
            raise click.ClickException(
                "--dev requires running from the root of the agents-cli repository"
            )
        tool_args = [
            "uv",
            "tool",
            "install",
            "--force",
            "--editable",
            str(project_root),
        ]
    else:
        tool_args = ["uv", "tool", "install", "google-agents-cli"]
    result = run(tool_args, capture=True, check=False)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if "already installed" in stdout.lower() or "already installed" in stderr.lower():
        from google.agents.cli.scaffold.utils.version import check_for_updates

        needs_update, current, latest = check_for_updates()
        if needs_update:
            click.secho(
                f"  Installed ({current}), but {latest} is available.",
                fg="yellow",
            )
            click.secho(
                "  Run 'uv tool upgrade google-agents-cli' to update.",
                dim=True,
            )
        else:
            click.secho("  Already installed and up to date.", dim=True)
        cli_installed = True
    elif result.returncode != 0:
        click.secho("  Could not install agents-cli automatically.", fg="yellow")
        if stderr.strip():
            for line in stderr.strip().splitlines():
                click.echo(f"  {line}")
        click.secho("  Install manually: uv tool install google-agents-cli", dim=True)
    else:
        for line in stdout.strip().splitlines():
            click.echo(f"  {line}")
        cli_installed = True

    # ── Skills Installation ──
    _print_section(step, "Skills Installation")
    step += 1
    click.echo()
    summary_lines = _run_npx_skills(args, "Installing skills")

    # ── Summary ──
    _print_section(step, "Summary")
    click.echo()

    # Auth status
    if skip_auth:
        click.echo("  Auth:   Skipped")
    else:
        from google.agents.cli.auth import is_authenticated

        authed, display = is_authenticated()
        if authed:
            click.echo(f"  Auth:   {display}")
        else:
            click.echo("  Auth:   Not authenticated")

    # CLI tool status
    if cli_installed:
        if dev:
            click.echo("  CLI:    agents-cli installed (editable)")
        else:
            click.echo("  CLI:    agents-cli installed")
    else:
        click.echo("  CLI:    Not installed (run: uv tool install google-agents-cli)")

    # Skills status
    if summary_lines:
        click.echo(f"  Skills: {summary_lines[0]}")
        for line in summary_lines[1:]:
            click.echo(f"          {line}")
    else:
        click.echo("  Skills: Installed")
    click.echo(f"  Scope:  {scope}")

    click.echo()
    click.secho("  Done.", fg="green", bold=True)
    click.echo()
