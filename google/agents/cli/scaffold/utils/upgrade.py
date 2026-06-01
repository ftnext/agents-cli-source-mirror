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

"""3-way file comparison and dependency merging for upgrade command."""

import fnmatch
import hashlib
import json
import logging
import pathlib
import re
import tomllib
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

# Patterns use {agent_directory} placeholder replaced at runtime
FILE_CATEGORIES = {
    "agent_code": [  # Never modified
        # Python agent code
        "{agent_directory}/agent.py",
        "{agent_directory}/tools/**/*.py",
        "{agent_directory}/prompts/**/*.py",
        # Go agent code
        "{agent_directory}/agent.go",
        "{agent_directory}/**/*.go",
        # Java agent code
        "{agent_directory}/**/*.java",
        # TypeScript agent code
        "{agent_directory}/agent.ts",
        "{agent_directory}/**/*.ts",
    ],
    "config_files": [  # Never overwritten
        "deployment/vars/*.tfvars",
        ".env",
        "*.env",
    ],
    "dependencies": [  # Special merge handling
        # ACLI config
        "agents-cli-manifest.yaml",
        # Python dependencies
        "pyproject.toml",
        # Go dependencies
        "go.mod",
        "go.sum",
        # Java dependencies (ACLI config is in pom.xml properties)
        "pom.xml",
        # TypeScript dependencies
        "package.json",
        "package-lock.json",
    ],
    # Everything else is "scaffolding" (3-way compare)
}


# Preserve type literals for type-safe reason matching
PreserveType = Literal["acli_unchanged", "already_current", "unchanged_both", None]


@dataclass
class FileCompareResult:
    """Result of comparing a file across three versions."""

    path: str
    category: str
    action: Literal["auto_update", "preserve", "skip", "conflict", "new", "removed"]
    reason: str
    # For preserve actions, indicates why preserved
    preserve_type: PreserveType = None
    # For conflicts, store the content hashes
    current_hash: str | None = None
    old_template_hash: str | None = None
    new_template_hash: str | None = None


@dataclass
class DependencyChange:
    """A single dependency change."""

    name: str
    change_type: Literal["updated", "added", "removed", "kept"]
    old_version: str | None = None
    new_version: str | None = None


@dataclass
class DependencyMergeResult:
    """Result of merging dependencies."""

    changes: list[DependencyChange] = field(default_factory=list)
    merged_deps: list[str] = field(default_factory=list)
    has_conflicts: bool = False


def _expand_patterns(patterns: list[str], agent_directory: str) -> list[str]:
    """Expand {agent_directory} placeholder in patterns."""
    return [p.replace("{agent_directory}", agent_directory) for p in patterns]


def _matches_any_pattern(path: str, patterns: list[str]) -> bool:
    """Check if path matches any glob pattern, including ** recursive patterns."""
    path = path.replace("\\", "/")

    for pattern in patterns:
        pattern = pattern.replace("\\", "/")

        if fnmatch.fnmatch(path, pattern):
            return True

        if "**" in pattern:
            regex = re.escape(pattern)
            regex = regex.replace(r"\*\*/", "(?:.*/)?")  # **/ = zero or more dirs
            regex = regex.replace(r"\*\*", ".*")
            regex = regex.replace(r"\*", "[^/]*")
            if re.match(f"^{regex}$", path):
                return True

    return False


def categorize_file(path: str, agent_directory: str = "app") -> str:
    """Return category: agent_code, config_files, dependencies, or scaffolding."""
    for category, patterns in FILE_CATEGORIES.items():
        expanded = _expand_patterns(patterns, agent_directory)
        if _matches_any_pattern(path, expanded):
            return category
    return "scaffolding"


def _file_hash(file_path: pathlib.Path) -> str | None:
    """Calculate SHA256 hash of a file's contents."""
    if not file_path.exists():
        return None
    try:
        content = file_path.read_bytes()
        return hashlib.sha256(content).hexdigest()
    except Exception as e:
        logging.warning(f"Could not hash file {file_path}: {e}")
        return None


def three_way_compare(
    relative_path: str,
    project_dir: pathlib.Path,
    old_template_dir: pathlib.Path,
    new_template_dir: pathlib.Path,
    agent_directory: str = "app",
) -> FileCompareResult:
    """Compare file across current, old template, and new template.

    Returns action based on:
    - current == old -> auto-update (user didn't modify)
    - old == new -> preserve (ACLI didn't change)
    - all differ -> conflict
    """
    category = categorize_file(relative_path, agent_directory)

    if category == "agent_code":
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="skip",
            reason="Agent code (never modified by upgrade)",
        )

    if category == "config_files":
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="skip",
            reason="Config file (user's environment settings)",
        )

    if category == "dependencies":
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="preserve",
            reason="Dependencies (requires merge handling)",
        )

    current_file = project_dir / relative_path
    old_template_file = old_template_dir / relative_path
    new_template_file = new_template_dir / relative_path

    current_hash = _file_hash(current_file)
    old_hash = _file_hash(old_template_file)
    new_hash = _file_hash(new_template_file)

    # New file in ACLI (not in project, regardless of old template)
    if current_hash is None and new_hash is not None:
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="new",
            reason="New file in ACLI",
            new_template_hash=new_hash,
        )

    # File removed in new template
    if current_hash is not None and old_hash is not None and new_hash is None:
        if current_hash == old_hash:
            return FileCompareResult(
                path=relative_path,
                category=category,
                action="removed",
                reason="File removed in ACLI (you didn't modify it)",
                current_hash=current_hash,
                old_template_hash=old_hash,
            )
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="conflict",
            reason="File removed in ACLI but you modified it",
            current_hash=current_hash,
            old_template_hash=old_hash,
        )

    # File only in current project (user-added, not part of ACLI template)
    if current_hash is not None and old_hash is None and new_hash is None:
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="skip",
            reason="User-added file (not part of ACLI template)",
        )

    # File doesn't exist anywhere relevant
    if current_hash is None and new_hash is None:
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="skip",
            reason="File not present",
        )

    # User didn't modify (current == old)
    if current_hash == old_hash and new_hash is not None:
        if old_hash == new_hash:
            return FileCompareResult(
                path=relative_path,
                category=category,
                action="preserve",
                reason="Unchanged in both project and ACLI",
                preserve_type="unchanged_both",
                current_hash=current_hash,
                old_template_hash=old_hash,
                new_template_hash=new_hash,
            )
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="auto_update",
            reason="You didn't modify this file",
            current_hash=current_hash,
            old_template_hash=old_hash,
            new_template_hash=new_hash,
        )

    # ACLI didn't change (old == new)
    if old_hash == new_hash and current_hash is not None:
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="preserve",
            reason="ACLI didn't change this file",
            preserve_type="acli_unchanged",
            current_hash=current_hash,
            old_template_hash=old_hash,
            new_template_hash=new_hash,
        )

    # Already up to date (current == new)
    if current_hash == new_hash:
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="preserve",
            reason="Already up to date",
            preserve_type="already_current",
            current_hash=current_hash,
            old_template_hash=old_hash,
            new_template_hash=new_hash,
        )

    # Migrated eval dataset: present in project + new template but not the old
    # one (the old template shipped evalsets/, not datasets/). This is the
    # converted user content from migrate_legacy_evalsets; preserve it rather
    # than treating it as a conflict against the stock default.
    if (
        old_hash is None
        and relative_path.startswith(_NEW_DATASETS_DIR + "/")
        and relative_path.endswith("-dataset.json")
    ):
        return FileCompareResult(
            path=relative_path,
            category=category,
            action="preserve",
            reason="Migrated eval dataset (your content)",
            preserve_type="acli_unchanged",
            current_hash=current_hash,
            old_template_hash=old_hash,
            new_template_hash=new_hash,
        )

    # All three differ -> conflict
    return FileCompareResult(
        path=relative_path,
        category=category,
        action="conflict",
        reason="Both you and ACLI modified this file",
        current_hash=current_hash,
        old_template_hash=old_hash,
        new_template_hash=new_hash,
    )


def collect_all_files(
    project_dir: pathlib.Path,
    old_template_dir: pathlib.Path,
    new_template_dir: pathlib.Path,
    exclude_patterns: list[str] | None = None,
) -> set[str]:
    """Collect all unique relative file paths from all three directories."""
    if exclude_patterns is None:
        exclude_patterns = [
            ".git/**",
            ".venv/**",
            "venv/**",
            "__pycache__/**",
            "*.pyc",
            ".DS_Store",
            "*.egg-info/**",
            "uv.lock",
            ".uv/**",
            "starter_pack_*",
        ]

    all_files: set[str] = set()

    for base_dir in [project_dir, old_template_dir, new_template_dir]:
        if not base_dir.exists():
            continue
        for file_path in base_dir.rglob("*"):
            if file_path.is_file():
                relative = str(file_path.relative_to(base_dir))
                # Check exclusions using _matches_any_pattern for ** support
                if not _matches_any_pattern(relative, exclude_patterns):
                    all_files.add(relative)

    return all_files


def _parse_dependency(dep_str: str) -> tuple[str, str, str]:
    """Parse a dependency string into (base_name, extras, version_spec).

    Extras are separated from the package name so that packages with
    different extras brackets (e.g., ``pkg[a]`` vs ``pkg[a,b]``) are
    keyed by the same base name.

    Examples:
        "google-adk>=0.2.0" -> ("google-adk", "", ">=0.2.0")
        "google-cloud-aiplatform[evaluation]>=1.0" -> ("google-cloud-aiplatform", "[evaluation]", ">=1.0")
        "requests==2.31.0" -> ("requests", "", "==2.31.0")
        "pytest" -> ("pytest", "", "")
    """
    # Match base package name, optional extras in brackets, optional version spec
    match = re.match(r"^([a-zA-Z0-9_-]+)(\[[^\]]+\])?(.*)", dep_str.strip())
    if match:
        base_name = match.group(1).lower()
        extras = match.group(2) or ""
        version = match.group(3).strip()
        return base_name, extras, version
    return dep_str.lower(), "", ""


def _load_dependencies_from_pyproject(
    pyproject_path: pathlib.Path,
) -> dict[str, tuple[str, str]]:
    """Load dependencies as {base_name: (extras, version_spec)} dict."""
    if not pyproject_path.exists():
        return {}

    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        deps = data.get("project", {}).get("dependencies", [])
        result: dict[str, tuple[str, str]] = {}
        for dep in deps:
            name, extras, version = _parse_dependency(dep)
            result[name] = (extras, version)
        return result
    except Exception as e:
        logging.warning(f"Error loading dependencies from {pyproject_path}: {e}")
        return {}


def merge_pyproject_dependencies(
    current_pyproject: pathlib.Path,
    old_template_pyproject: pathlib.Path,
    new_template_pyproject: pathlib.Path,
) -> DependencyMergeResult:
    """Merge deps: new_template + user_added, where user_added = current - old."""
    current_deps = _load_dependencies_from_pyproject(current_pyproject)
    old_deps = _load_dependencies_from_pyproject(old_template_pyproject)
    new_deps = _load_dependencies_from_pyproject(new_template_pyproject)

    changes: list[DependencyChange] = []
    merged: dict[str, tuple[str, str]] = {}
    user_added = set(current_deps.keys()) - set(old_deps.keys())
    acli_managed = set(old_deps.keys())

    for name, (new_extras, new_version) in new_deps.items():
        merged[name] = (new_extras, new_version)

        if name in old_deps:
            old_extras, old_version = old_deps[name]
            old_spec = f"{old_extras}{old_version}"
            new_spec = f"{new_extras}{new_version}"
            if old_spec != new_spec:
                changes.append(
                    DependencyChange(
                        name=name,
                        change_type="updated",
                        old_version=old_spec,
                        new_version=new_spec,
                    )
                )
        else:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="added",
                    new_version=f"{new_extras}{new_version}",
                )
            )

    for name in user_added:
        user_extras, user_version = current_deps[name]
        merged[name] = (user_extras, user_version)
        user_spec = f"{user_extras}{user_version}"
        changes.append(
            DependencyChange(
                name=name,
                change_type="kept",
                old_version=user_spec,
                new_version=user_spec,
            )
        )

    for name in acli_managed:
        if name not in new_deps and name not in user_added:
            old_extras, old_version = old_deps[name]
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="removed",
                    old_version=f"{old_extras}{old_version}",
                )
            )

    merged_list = [
        f"{name}{extras}{version}" for name, (extras, version) in sorted(merged.items())
    ]

    return DependencyMergeResult(
        changes=changes,
        merged_deps=merged_list,
        has_conflicts=False,
    )


def write_merged_dependencies(
    pyproject_path: pathlib.Path,
    merged_deps: list[str],
) -> bool:
    """Write merged dependencies to pyproject.toml using uv CLI.

    Uses ``uv add --frozen`` and ``uv remove --frozen`` so the lockfile
    and virtualenv are left untouched — only pyproject.toml is modified.

    Args:
        pyproject_path: Path to pyproject.toml
        merged_deps: List of dependency strings to write

    Returns:
        True if successful, False otherwise
    """
    if not pyproject_path.exists():
        return False

    project_dir = pyproject_path.parent

    try:
        from google.agents.cli._runner import run_resolved
        from google.agents.cli._tools import ToolNotFoundError

        # Determine which deps to remove (in current but not in merged)
        current_deps = _load_dependencies_from_pyproject(pyproject_path)
        merged_names: set[str] = set()
        for dep in merged_deps:
            name, _, _ = _parse_dependency(dep)
            merged_names.add(name)

        to_remove = [n for n in current_deps if n not in merged_names]

        if to_remove:
            result = run_resolved(
                ["uv", "remove", "--frozen", *to_remove],
                cwd=project_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logging.warning(f"uv remove failed: {result.stderr}")

        # Add / update all merged deps
        if merged_deps:
            result = run_resolved(
                ["uv", "add", "--frozen", *merged_deps],
                cwd=project_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logging.warning(f"uv add failed: {result.stderr}")
                return False

        return True
    # run_resolved raises ToolNotFoundError if the executable is not found
    except ToolNotFoundError:
        logging.warning("uv not found — cannot write merged dependencies")
        return False
    except Exception as e:
        logging.warning(f"Could not write dependencies to {pyproject_path}: {e}")
        return False


def update_acli_metadata(
    project_dir: pathlib.Path,
    create_params: dict[str, str],
    acli_version: str | None = None,
    language: str = "python",
    remove_keys: list[str] | None = None,
) -> bool:
    """Update specific keys in the unified agents-cli-manifest.yaml metadata file.

    Args:
        project_dir: Path to the project directory
        create_params: Dict of keys to update inside create_params
        acli_version: If provided, update acli_version
        language: Project language (unused now as config file is fixed)
        remove_keys: List of keys to remove from create_params section

    Returns:
        True if successful, False otherwise
    """
    manifest_path = project_dir / "agents-cli-manifest.yaml"
    if not manifest_path.exists():
        logging.warning(f"Manifest not found: {manifest_path}")
        return False

    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if acli_version:
            data["acli_version"] = acli_version

        if "create_params" not in data or not isinstance(data["create_params"], dict):
            data["create_params"] = {}

        params = data["create_params"]

        for key, val in create_params.items():
            params[key] = val

        if remove_keys:
            for key in remove_keys:
                params.pop(key, None)

        with open(manifest_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        logging.warning(f"Could not update ACLI metadata in {manifest_path}: {e}")
        return False


def migrate_legacy_python_config(
    project_dir: pathlib.Path, dry_run: bool = False
) -> None:
    """Extract legacy [tool.agents-cli] config from pyproject.toml and write to agents-cli-manifest.yaml."""
    pyproject_path = project_dir / "pyproject.toml"
    manifest_path = project_dir / "agents-cli-manifest.yaml"

    if not pyproject_path.exists():
        return

    import tomlkit

    content = pyproject_path.read_text(encoding="utf-8")
    doc = tomlkit.parse(content)

    tool_section = doc.get("tool", {})
    acli = tool_section.get("agents-cli")
    if acli is None:
        return

    if manifest_path.exists():
        import click

        click.secho(
            "  ▸ Legacy [tool.agents-cli] section found in pyproject.toml but agents-cli-manifest.yaml already exists. The legacy config will be ignored and that section can be safely deleted.",
            fg="yellow",
            dim=True,
        )
        return

    if dry_run:
        import click

        click.secho(
            "  ▸ [Dry run] Legacy pyproject.toml configuration would be migrated to agents-cli-manifest.yaml",
            fg="yellow",
            dim=True,
        )
        return

    # Reconstruct new manifest content
    manifest_data = {}
    project_section = doc.get("project", {})
    name = project_section.get("name") or acli.get("name")
    if name:
        manifest_data["name"] = str(name)

    # Copy all config parameters directly, except name
    acli_unwrapped = acli.unwrap()
    for k, v in acli_unwrapped.items():
        if k != "name" and v is not None:
            manifest_data[k] = v

    import yaml

    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest_data, f, default_flow_style=False, sort_keys=False)

    # Remove legacy tool config lines from pyproject.toml last, after manifest write succeeds
    del tool_section["agents-cli"]
    if not tool_section:
        del doc["tool"]
    pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    import click

    click.secho(
        "  ▸ Legacy pyproject.toml configuration successfully migrated to agents-cli-manifest.yaml",
        fg="cyan",
        dim=True,
    )


_LEGACY_EVALSETS_DIR = "tests/eval/evalsets"
_NEW_DATASETS_DIR = "tests/eval/datasets"
_LEGACY_EVALSET_GLOB = "*.evalset.json"
_LEGACY_EVAL_CONFIG = "tests/eval/eval_config.json"
_NEW_EVAL_CONFIG = "tests/eval/eval_config.yaml"
_EVAL_MIGRATION_URL = (
    "https://google.github.io/agents-cli/reference/eval-dataset-migration/"
)


def _convert_eval_case(old_case: dict[str, Any]) -> dict[str, Any]:
    new_case: dict[str, Any] = {}
    case_id = old_case.get("eval_id") or old_case.get("eval_case_id")
    if case_id:
        new_case["eval_case_id"] = case_id

    conversation = old_case.get("conversation") or []
    if not conversation:
        return new_case

    if len(conversation) == 1:
        turn = conversation[0]
        user_parts = (turn.get("user_content") or {}).get("parts") or []
        new_case["prompt"] = {"role": "user", "parts": user_parts}
        final_response = turn.get("final_response")
        if final_response:
            new_case["reference"] = {
                "response": {
                    "role": "model",
                    "parts": final_response.get("parts") or [],
                }
            }
        return new_case

    events: list[dict[str, Any]] = []
    last_idx = len(conversation) - 1
    for i, turn in enumerate(conversation):
        user_parts = (turn.get("user_content") or {}).get("parts") or []
        events.append(
            {
                "author": "user",
                "content": {"role": "user", "parts": user_parts},
            }
        )
        final_response = turn.get("final_response")
        if not final_response:
            continue
        if i < last_idx:
            events.append(
                {
                    "author": "agent",
                    "content": {
                        "role": "model",
                        "parts": final_response.get("parts") or [],
                    },
                }
            )
        else:
            new_case["reference"] = {
                "response": {
                    "role": "model",
                    "parts": final_response.get("parts") or [],
                }
            }
    new_case["agent_data"] = {
        "turns": [{"turn_index": 0, "events": events}],
    }
    return new_case


def _convert_eval_set(old_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "eval_cases": [
            _convert_eval_case(c) for c in (old_payload.get("eval_cases") or [])
        ]
    }


def _legacy_to_new_filename(legacy_name: str) -> str:
    stem = legacy_name[: -len(".evalset.json")]
    return f"{stem}-dataset.json"


def migrate_legacy_evalsets(project_dir: pathlib.Path, dry_run: bool = False) -> None:
    """Convert tests/eval/evalsets/*.evalset.json to tests/eval/datasets/*-dataset.json.

    No-op when the legacy directory is absent. Skips destination files
    that already exist. Does not delete the legacy directory; the user
    removes it after verifying the conversion.
    """
    import click

    legacy_dir = project_dir / _LEGACY_EVALSETS_DIR
    if not legacy_dir.is_dir():
        return

    legacy_files = sorted(legacy_dir.glob(_LEGACY_EVALSET_GLOB))
    if not legacy_files:
        return

    output_dir = project_dir / _NEW_DATASETS_DIR

    if dry_run:
        count = len(legacy_files)
        noun = "file" if count == 1 else "files"
        click.secho(
            f"  ▸ [Dry run] {count} legacy eval {noun} would be migrated "
            f"to {_NEW_DATASETS_DIR}/",
            fg="yellow",
            dim=True,
        )
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    converted = 0
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    for src in legacy_files:
        dest = output_dir / _legacy_to_new_filename(src.name)
        if dest.exists():
            skipped.append(dest.name)
            continue
        try:
            old_payload = json.loads(src.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            failed.append((src.name, str(e)))
            continue
        new_payload = _convert_eval_set(old_payload)
        dest.write_text(json.dumps(new_payload, indent=2) + "\n", encoding="utf-8")
        converted += 1

    if converted:
        noun = "file" if converted == 1 else "files"
        click.secho(
            f"  ▸ Migrated {converted} legacy eval {noun} to {_NEW_DATASETS_DIR}/. "
            "Run `agents-cli eval generate` to populate the trace.",
            fg="cyan",
            dim=True,
        )
    if skipped:
        click.secho(
            f"  ▸ WARNING: did NOT migrate {len(skipped)} legacy eval file(s) — "
            f"a file already exists at the destination: {', '.join(skipped)}. "
            f"The legacy file(s) remain in {_LEGACY_EVALSETS_DIR}/ unconverted. "
            "Reconcile manually before deleting the legacy directory.",
            fg="yellow",
            bold=True,
        )
    if failed:
        for name, err in failed:
            click.secho(f"  ▸ Failed to migrate {name}: {err}", fg="red", dim=True)
        click.secho(
            f"  ▸ See migration guide: {_EVAL_MIGRATION_URL}",
            fg="yellow",
            dim=True,
        )
    if converted and not skipped and not failed:
        click.secho(
            f"  ▸ All legacy evalsets migrated. You can delete "
            f"{_LEGACY_EVALSETS_DIR}/ once you've verified the converted files.",
            fg="cyan",
            dim=True,
        )


def warn_legacy_eval_config(project_dir: pathlib.Path) -> None:
    """Warn if a legacy tests/eval/eval_config.json is left over after upgrade."""
    import click

    if not (project_dir / _LEGACY_EVAL_CONFIG).is_file():
        return

    click.secho(
        f"  ▸ WARNING: found legacy {_LEGACY_EVAL_CONFIG}. Grading now reads "
        f"{_NEW_EVAL_CONFIG}; your custom criteria will NOT apply until "
        f"migrated. The two schemas differ, so this is not auto-converted. "
        f"See migration guide: {_EVAL_MIGRATION_URL}",
        fg="yellow",
        bold=True,
    )


def compare_all_files(
    project_dir: pathlib.Path,
    old_template_dir: pathlib.Path,
    new_template_dir: pathlib.Path,
    agent_directory: str = "app",
) -> list[FileCompareResult]:
    """Compare all files using 3-way comparison."""
    all_files = collect_all_files(project_dir, old_template_dir, new_template_dir)

    results = []
    for relative_path in sorted(all_files):
        result = three_way_compare(
            relative_path,
            project_dir,
            old_template_dir,
            new_template_dir,
            agent_directory,
        )
        results.append(result)

    return results


def group_results_by_action(
    results: list[FileCompareResult],
) -> dict[str, list[FileCompareResult]]:
    """Group results by action type."""
    groups: dict[str, list[FileCompareResult]] = {
        "auto_update": [],
        "preserve": [],
        "skip": [],
        "conflict": [],
        "new": [],
        "removed": [],
    }

    for result in results:
        groups[result.action].append(result)

    return groups
