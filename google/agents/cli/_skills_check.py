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

"""Skills version drift detection for agents-cli."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import click
import yaml

# Pin the skills npm package to avoid executing an unverified version.
SKILLS_NPX_PACKAGE = "skills@1.4.8"

_SKILLS_CHECK_INTERVAL = 12 * 60 * 60  # 12 hours in seconds
_SKILLS_CHECK_STAMP = Path.home() / ".agents" / ".acli_skills_check"


def _parse_skill_version(skill_md: Path) -> str | None:
    """Extract ``metadata.version`` from a SKILL.md YAML frontmatter.

    Returns the version string, or ``None`` on any failure.
    Warns to stderr when the file exists but cannot be parsed.
    """
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None

    if not content.startswith("---"):
        logging.warning(f"Malformed skill file (no frontmatter): {skill_md}")
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        logging.warning(f"Malformed skill file (incomplete frontmatter): {skill_md}")
        return None
    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        logging.warning(f"Malformed skill file (invalid YAML): {skill_md}")
        return None

    version = (frontmatter or {}).get("metadata", {}).get("version")
    if not version:
        logging.warning(f"Malformed skill file (missing metadata.version): {skill_md}")
    return str(version) if version else None


def _find_installed_skills() -> dict[str, str]:
    """Return ``{skill_name: version}`` for every installed agents-cli skill.

    Fast path (~8 ms): scan ``~/.agents/skills/google-agents-cli-*/SKILL.md``
    directly.  Falls back to ``npx skills list --json`` (~400 ms+) if
    the well-known directory is empty or missing, which is more robust
    when skills are installed to a non-default location.
    """
    import json
    import subprocess

    result: dict[str, str] = {}

    # Fast path: well-known global install location
    skills_dir = Path.home() / ".agents" / "skills"
    if skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.name.startswith("google-agents-cli-"):
                continue
            version = _parse_skill_version(skill_dir / "SKILL.md")
            if version:
                result[skill_dir.name] = version

    if result:
        return result

    # Slow path: ask npx skills for actual install locations
    try:
        from google.agents.cli._tools import get_npx_path

        npx_path = get_npx_path()
        proc = subprocess.run(
            [npx_path, "-y", "skills", "list", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if proc.returncode != 0:
            return {}
        for entry in json.loads(proc.stdout):
            name = entry.get("name", "")
            if not name.startswith("google-agents-cli-"):
                continue
            candidate = Path(entry["path"]) / "SKILL.md"
            version = _parse_skill_version(candidate)
            if version:
                result[name] = version
    except Exception:
        pass

    return result


def get_installed_skills() -> list[dict] | None:
    """Return installed agents-cli skills as a list of dicts.

    Returns None if the query fails.
    """
    import json
    import subprocess

    try:
        from google.agents.cli._tools import get_npx_path

        npx_path = get_npx_path()
        result = subprocess.run(
            [npx_path, "-y", SKILLS_NPX_PACKAGE, "list", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logging.warning(
                "npx skills list failed (exit %d): %s",
                result.returncode,
                result.stderr.strip(),
            )
            return None
        skills = json.loads(result.stdout)
        return [s for s in skills if s.get("name", "").startswith("google-agents-cli-")]
    except Exception as e:
        logging.warning("Could not query installed skills: %s", e)
        return None


def _skills_check_is_due() -> bool:
    """Return True if enough time has elapsed since the last check."""
    try:
        last = float(_SKILLS_CHECK_STAMP.read_text().strip())
        return (time.time() - last) > _SKILLS_CHECK_INTERVAL
    except (OSError, ValueError):
        return True


def _record_skills_check() -> None:
    """Write the current timestamp to the stamp file."""
    try:
        _SKILLS_CHECK_STAMP.parent.mkdir(parents=True, exist_ok=True)
        _SKILLS_CHECK_STAMP.write_text(str(time.time()))
    except OSError:
        pass


def check_skills_version() -> None:
    """Warn if any installed skill version doesn't match the running CLI version.

    Rate-limited to once per 24 hours via a timestamp file so it can
    run globally on every command without adding latency.

    Scans all installed ``google-agents-cli-*`` skills, compares each
    ``metadata.version`` with the running ``__version__``, and lists
    the mismatched ones.  Never blocks execution.
    """
    if not _skills_check_is_due():
        return

    installed = _find_installed_skills()
    if not installed:
        return

    from google.agents.cli import __version__

    _record_skills_check()

    mismatched = {name: ver for name, ver in installed.items() if ver != __version__}
    if not mismatched:
        return

    lines = [f"  - {name} (v{ver})" for name, ver in mismatched.items()]
    click.echo(
        f"\n⚠️  Skills version mismatch — CLI is v{__version__}, "
        f"but {len(mismatched)} skill(s) differ:\n"
        + "\n".join(lines)
        + "\n   Run 'agents-cli update' to sync.\n"
    )
