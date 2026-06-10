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

"""Shared language configuration and utilities for CLI commands.

This module centralizes language-specific configuration (Python, Go, Java, TypeScript)
used by enhance and upgrade commands. It provides:

- LANGUAGE_CONFIGS: Configuration dict for each supported language
- get_language_config(): Get config dict for a language
"""

import pathlib
from typing import Any

# =============================================================================
# Language Configuration
# =============================================================================
# To add a new language, add an entry with the required keys.

LANGUAGE_CONFIGS: dict[str, dict[str, Any]] = {
    "python": {
        "lock_file": "uv.lock",
        "lock_command": ["uv", "lock"],
        "lock_command_name": "uv lock",
        "strip_dependencies": True,
        "display_name": "Python",
        "agent_file": "agent.py",
        "agent_variable": "root_agent",
        "agent_in_subdirectory": False,
    },
    "go": {
        "lock_file": "go.sum",
        "lock_command": ["go", "mod", "tidy"],
        "lock_command_name": "go mod tidy",
        "strip_dependencies": False,
        "display_name": "Go",
        "agent_file": "agent.go",
        "agent_variable": "RootAgent",
        "agent_in_subdirectory": False,
    },
    "java": {
        "lock_file": None,  # Maven doesn't have a separate lock file
        "lock_command": ["mvn", "dependency:resolve"],
        "lock_command_name": "mvn dependency:resolve",
        "strip_dependencies": False,
        "display_name": "Java",
        "agent_file": "Agent.java",
        "agent_file_pattern": "**/Agent.java",
        "agent_variable": "ROOT_AGENT",
        "agent_in_subdirectory": True,  # Java uses package subdirectories
    },
    "typescript": {
        "lock_file": "package-lock.json",
        "lock_command": ["npm", "install", "--package-lock-only"],
        "lock_command_name": "npm install --package-lock-only",
        "strip_dependencies": False,
        "display_name": "TypeScript",
        "agent_file": "agent.ts",
        "agent_variable": "rootAgent",
        "agent_in_subdirectory": False,
    },
}


def get_language_config(language: str) -> dict[str, Any]:
    """Get the configuration dict for a language.

    Args:
        language: Language key (e.g., 'python', 'go')

    Returns:
        The language configuration dict, or Python config as fallback
    """
    return LANGUAGE_CONFIGS.get(language, LANGUAGE_CONFIGS["python"])


def find_agent_file(
    project_dir: pathlib.Path,
    language: str,
    agent_directory: str,
) -> pathlib.Path | None:
    """Find the primary agent file for a language.

    For Python: {agent_directory}/agent.py
    For Go: {agent_directory}/agent.go
    For Java: {agent_directory}/**/Agent.java (searches package subdirectories)
    For TypeScript: {agent_directory}/agent.ts

    Args:
        project_dir: Project root directory
        language: Language key ('python', 'go', 'java', 'typescript')
        agent_directory: Agent directory relative to project root

    Returns:
        Path to agent file if found, None otherwise
    """
    lang_config = get_language_config(language)
    agent_folder = project_dir / agent_directory

    if not agent_folder.exists():
        return None

    # Check for YAML config agent first (all languages)
    yaml_agent = agent_folder / "root_agent.yaml"
    if yaml_agent.exists():
        return yaml_agent

    agent_file_name = lang_config.get("agent_file")
    if not agent_file_name:
        return None

    # For languages with agent in subdirectory (Java package structure)
    if lang_config.get("agent_in_subdirectory"):
        for found in agent_folder.rglob(agent_file_name):
            return found
        return None

    # Standard case: agent file directly in agent directory
    agent_file = agent_folder / agent_file_name
    return agent_file if agent_file.exists() else None


def validate_agent_file(
    agent_file: pathlib.Path,
    language: str,
) -> tuple[bool, str | None]:
    """Validate that the agent file contains the required variable.

    Args:
        agent_file: Path to the agent file
        language: Language key

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    lang_config = get_language_config(language)
    required_var = lang_config.get("agent_variable", "root_agent")

    # YAML config agents are always valid
    if agent_file.name == "root_agent.yaml":
        return True, None

    try:
        content = agent_file.read_text(encoding="utf-8")

        if required_var in content:
            return True, None
        else:
            return False, f"Missing '{required_var}' variable in {agent_file.name}"
    except Exception as e:
        return False, f"Could not read {agent_file.name}: {e}"


def get_agent_file_hint(
    dir_path: pathlib.Path,
    language: str | None = None,
) -> str:
    """Get hint string for directory selection.

    Args:
        dir_path: Directory to check
        language: Optional language hint

    Returns:
        Hint string like ' (has Agent.java)' or ''
    """
    if not dir_path.is_dir():
        return ""

    # Check YAML config agent first
    if (dir_path / "root_agent.yaml").exists():
        return " (has root_agent.yaml)"

    # Check for Java Agent.java (in subdirectories)
    if any(dir_path.rglob("Agent.java")):
        return " (has Agent.java)"

    # Check for Go agent.go
    if (dir_path / "agent.go").exists():
        return " (has agent.go)"

    # Check for TypeScript agent.ts
    if (dir_path / "agent.ts").exists():
        return " (has agent.ts)"

    # Check for Python agent.py
    if (dir_path / "agent.py").exists():
        return " (has agent.py)"

    return ""


def get_project_version(
    project_dir: str | pathlib.Path,
    default_version: str = "0.0.0",
) -> str:
    """Extract the project version field from pyproject.toml if it exists.

    Args:
        project_dir: The project root directory.
        default_version: The fallback version to return if not found.

    Returns:
        The extracted version string, or default_version.
    """
    import logging
    import tomllib
    from pathlib import Path

    root = Path(project_dir)
    pyproject_path = root / "pyproject.toml"

    try:
        if not pyproject_path.exists():
            raise FileNotFoundError(f"pyproject.toml not found in {project_dir}")

        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        # Standard PEP 621 [project] section
        version = data.get("project", {}).get("version")
        if version and isinstance(version, str):
            return version
        else:
            raise KeyError(
                f"Could not find project version in pyproject.toml under {project_dir}"
            )
    except Exception as e:
        logging.warning(
            "Could not read the project version from the [project].version field "
            "of %s (%s). Falling back to %s — set the version in pyproject.toml, "
            "or pass AGENT_VERSION via --update-env-vars to override.",
            pyproject_path,
            e,
            default_version,
        )

    return default_version
