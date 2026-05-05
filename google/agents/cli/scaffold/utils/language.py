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
- detect_language(): Detect project language from files
- get_acli_config_for_language(): Read ACLI config based on language
- get_language_config(): Get config dict for a language
- update_acli_version(): Update version in appropriate config file
"""

import logging
import pathlib
import re
import tomllib
import xml.etree.ElementTree as ET
from typing import Any

# =============================================================================
# Language Configuration
# =============================================================================
# To add a new language, add an entry with the required keys.

LANGUAGE_CONFIGS: dict[str, dict[str, Any]] = {
    "python": {
        "detection_files": ["pyproject.toml"],
        "config_file": "pyproject.toml",
        "config_path": ["tool", "agents-cli"],
        "version_key": "acli_version",
        "project_files": ["pyproject.toml"],
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
        "detection_files": ["go.mod"],
        "config_file": ".acli.toml",
        "config_path": ["project"],
        "version_key": "version",
        "project_files": ["go.mod", "go.sum", ".acli.toml"],
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
        "detection_files": ["pom.xml"],
        "config_file": "pom.xml",
        "config_format": "maven_properties",  # ACLI metadata stored as Maven properties
        "config_path": [],  # Not used for Maven - we look for acli.* properties
        "version_key": "acli.version",
        "project_files": ["pom.xml"],
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
        "detection_files": ["package.json", "tsconfig.json"],
        "config_file": ".acli.toml",
        "config_path": ["project"],
        "version_key": "version",
        "project_files": [
            "package.json",
            "package-lock.json",
            "tsconfig.json",
            "vitest.config.ts",
            "eslint.config.mjs",
            ".acli.toml",
        ],
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


def _read_maven_acli_properties(pom_path: pathlib.Path) -> dict[str, Any]:
    """Read ACLI properties from a Maven pom.xml file.

    Looks for properties with 'acli.' prefix in the <properties> section.

    Args:
        pom_path: Path to the pom.xml file

    Returns:
        Dict with ACLI properties (keys without 'acli.' prefix)
    """
    if not pom_path.exists():
        return {}

    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()

        # Handle Maven namespace
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        properties = root.find(f"{ns}properties")
        if properties is None:
            return {}

        result = {}
        for prop in properties:
            # Remove namespace from tag
            tag = prop.tag.replace(ns, "")
            if tag.startswith("acli."):
                # Remove 'acli.' prefix and store
                key = tag[5:]  # Remove 'acli.' prefix
                result[key] = prop.text
        return result
    except Exception as e:
        logging.debug(f"Could not read Maven properties from {pom_path}: {e}")
        return {}


def detect_language(project_dir: pathlib.Path) -> str:
    """Detect the project language using LANGUAGE_CONFIGS.

    Detection order:
    1. Check .acli.toml for explicit language field (Go)
    2. Check pom.xml for acli.language property (Java)
    3. Check for language-specific detection files (go.mod, pom.xml, pyproject.toml)
    4. Default to Python

    Args:
        project_dir: Path to the project directory

    Returns:
        Language key (e.g., 'python', 'go', 'java', 'typescript')
    """
    # First, check .acli.toml for explicit language declaration (Go, TypeScript use this)
    acli_toml_path = project_dir / ".acli.toml"
    if acli_toml_path.exists():
        try:
            with open(acli_toml_path, "rb") as f:
                acli_data = tomllib.load(f)
            language = acli_data.get("project", {}).get("language")
            if language and language in LANGUAGE_CONFIGS:
                return language
        except Exception:
            pass

    # Check pom.xml for acli.language property (Java uses this)
    pom_path = project_dir / "pom.xml"
    if pom_path.exists():
        acli_props = _read_maven_acli_properties(pom_path)
        if acli_props.get("language") == "java":
            return "java"

    # Check each language's detection files (non-Python first to avoid false positives)
    # Python has pyproject.toml which is common, so check other languages first
    # TypeScript also needs to be checked before Python since both can coexist
    for lang in [
        "go",
        "java",
        "typescript",
        "python",
    ]:  # Order matters: more specific first
        config = LANGUAGE_CONFIGS.get(lang)
        if config:
            detection_files = config.get("detection_files", [])
            # For TypeScript, require both package.json AND tsconfig.json
            if lang == "typescript":
                if all((project_dir / f).exists() for f in detection_files):
                    return lang
            else:
                for detection_file in detection_files:
                    if (project_dir / detection_file).exists():
                        return lang

    # Default to Python
    return "python"


def get_acli_config_for_language(
    project_dir: pathlib.Path, language: str
) -> dict[str, Any] | None:
    """Read ACLI config based on language configuration.

    Uses LANGUAGE_CONFIGS to determine where to look for config.

    - Python: Reads from pyproject.toml [tool.agents-cli]
    - Go: Reads from .acli.toml [project]
    - Java: Reads acli.* properties from pom.xml <properties>

    Args:
        project_dir: Path to the project directory
        language: Language key (e.g., 'python', 'go', 'java')

    Returns:
        The ACLI config dict if found, None otherwise
    """
    lang_config = LANGUAGE_CONFIGS.get(language)
    if not lang_config:
        return None

    config_file = lang_config.get("config_file")
    config_format = lang_config.get("config_format", "toml")

    if not config_file:
        return None

    config_file_path = project_dir / config_file
    if not config_file_path.exists():
        return None

    # Handle Maven properties format for Java
    if config_format == "maven_properties":
        acli_props = _read_maven_acli_properties(config_file_path)
        # Return None if no ACLI properties found
        if not acli_props:
            return None
        # Normalize key names: base_template, agent_directory, etc.
        # Maven properties use acli.base_template -> base_template
        return acli_props

    # Handle TOML format (Python, Go)
    config_path = lang_config.get("config_path", [])

    try:
        with open(config_file_path, "rb") as f:
            data = tomllib.load(f)

        # Navigate to the config path (e.g., ["tool", "agents-cli"])
        result = data
        for key in config_path:
            if isinstance(result, dict):
                result = result.get(key)
            else:
                return None
            if result is None:
                return None

        return result if isinstance(result, dict) else None
    except Exception as e:
        logging.debug(f"Could not read config from {config_file}: {e}")
        return None


def get_language_config(language: str) -> dict[str, Any]:
    """Get the configuration dict for a language.

    Args:
        language: Language key (e.g., 'python', 'go')

    Returns:
        The language configuration dict, or Python config as fallback
    """
    return LANGUAGE_CONFIGS.get(language, LANGUAGE_CONFIGS["python"])


def _update_maven_acli_property(
    pom_path: pathlib.Path, property_name: str, new_value: str
) -> bool:
    """Update an ACLI property in a Maven pom.xml file.

    Args:
        pom_path: Path to the pom.xml file
        property_name: Property name (e.g., 'acli.version')
        new_value: New value for the property

    Returns:
        True if successful, False otherwise
    """
    try:
        content = pom_path.read_text(encoding="utf-8")

        # Use regex to update the property value
        # Pattern matches: <acli.version>value</acli.version>
        pattern = rf"(<{property_name}>)[^<]*(</)"
        replacement = rf"\g<1>{new_value}\g<2>"
        updated_content = re.sub(pattern, replacement, content)

        if updated_content != content:
            pom_path.write_text(updated_content, encoding="utf-8")
            return True
        else:
            logging.warning(f"Could not find <{property_name}> in pom.xml")
            return False
    except Exception as e:
        logging.warning(f"Could not update {property_name} in pom.xml: {e}")
        return False


def update_acli_version(
    project_dir: pathlib.Path,
    language: str,
    new_version: str,
) -> bool:
    """Update the ACLI version in the appropriate config file.

    For Python: Updates acli_version in pyproject.toml [tool.agents-cli]
    For Go: Updates version in .acli.toml [project]
    For Java: Updates acli.version in pom.xml <properties>

    Args:
        project_dir: Path to project directory
        language: Language key (e.g., 'python', 'go', 'java')
        new_version: New ACLI version string

    Returns:
        True if successful, False otherwise
    """
    lang_config = get_language_config(language)
    config_file = lang_config.get("config_file")
    config_format = lang_config.get("config_format", "toml")
    version_key = lang_config.get("version_key", "acli_version")

    if not config_file:
        return False

    config_path = project_dir / config_file
    if not config_path.exists():
        return False

    # Handle Maven properties format for Java
    if config_format == "maven_properties":
        return _update_maven_acli_property(config_path, version_key, new_version)

    # Handle TOML format (Python, Go)
    try:
        content = config_path.read_text(encoding="utf-8")

        # Use regex to update the version key
        # Pattern matches: version_key = "value" or version_key = 'value'
        pattern = rf'({version_key}\s*=\s*")[^"]*(")'
        replacement = rf"\g<1>{new_version}\g<2>"
        updated_content = re.sub(pattern, replacement, content)

        # If no match with double quotes, try single quotes
        if updated_content == content:
            pattern = rf"({version_key}\s*=\s*')[^']*(')"
            replacement = rf"\g<1>{new_version}\g<2>"
            updated_content = re.sub(pattern, replacement, content)

        if updated_content != content:
            config_path.write_text(updated_content, encoding="utf-8")
            return True
        else:
            logging.warning(f"Could not find {version_key} in {config_file}")
            return False

    except Exception as e:
        logging.warning(f"Could not update {version_key} in {config_file}: {e}")
        return False


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
