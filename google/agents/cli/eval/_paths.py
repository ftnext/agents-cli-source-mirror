# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Canonical paths and file-name conventions for the eval module.

Single source of truth so eval commands stay consistent. Lifecycle stages:

  Stage 1 — eval cases ready for inference. Each case may use either:
      (a) a top-level ``prompt`` field (single user message), OR
      (b) ``agent_data`` whose turns end with a user message (continued
          conversation; ``eval generate`` appends the next agent
          response — the "N+1" pattern).
      Both shapes are valid input to ``eval generate``.
      Default location:  tests/eval/datasets/*.json
      Consumed by:       ``eval generate``
      Produced by:       scaffold (and, in future, ``eval dataset
                         synthesize`` when given a seed).

  Stage 2 — populated traces (eval cases with completed ``agent_data``,
            i.e. agent responses + tool calls already filled in):
      artifacts/traces/traces_<ts>.json
      Consumed by:  ``eval grade``
      Produced by:  ``eval generate``, ``eval dataset synthesize``.

  Stage 3 — graded results (scored evaluation):
      artifacts/grade_results/
      Consumed by:  ``eval analyze``
      Produced by:  ``eval grade``.

All four file kinds share the SDK type ``vertexai.types.EvaluationDataset``
as a container, but they are NOT interchangeable: the populated fields
differ by stage.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Top-level output directory (under the user's project root).
# ---------------------------------------------------------------------------

ARTIFACTS_DIR = "artifacts"

# ---------------------------------------------------------------------------
# Subdirectories under ARTIFACTS_DIR.
# ---------------------------------------------------------------------------

# Stage 2 — populated traces.
TRACES_SUBDIR = "traces"

# Stage 3 — graded results.
GRADE_RESULTS_SUBDIR = "grade_results"

# ---------------------------------------------------------------------------
# Canonical file-name prefixes (a timestamp + ".json" gets appended).
# ---------------------------------------------------------------------------

# Stage 2 file prefix. Same value as ``TRACES_SUBDIR`` by coincidence;
# the two constants exist because they play different roles at the call
# site (directory name vs. file-name prefix).
TRACES_FILE_PREFIX = "traces"

# ---------------------------------------------------------------------------
# Scaffolded inputs (under the user's project root).
# ---------------------------------------------------------------------------

# Stage 1 default — the file scaffolded by ``agents-cli create``.
DEFAULT_INPUT_DATASET = "tests/eval/datasets/basic-dataset.json"


def timestamp() -> str:
    """Return the canonical timestamp suffix used in default filenames."""
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def timestamped_artifact_path(directory: Path, prefix: str, ext: str = "json") -> Path:
    """Return ``{directory}/{prefix}_<ts>.{ext}``, creating ``directory``.

    Low-level helper used by eval commands that write a fresh, timestamped
    artifact file. Callers compose ``directory`` themselves so this helper
    works for both project-root-relative paths (e.g. ``project_root /
    ARTIFACTS_DIR / TRACES_SUBDIR``) and cwd-relative paths (e.g.
    ``Path(ARTIFACTS_DIR)``).
    """
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}_{timestamp()}.{ext}"


def default_traces_path(project_root: Path) -> Path:
    """Return the default stage-2 traces output path.

    Form: ``{project_root}/{ARTIFACTS_DIR}/{TRACES_SUBDIR}/traces_<ts>.json``.

    Creates the parent directory tree if it does not exist.
    """
    return timestamped_artifact_path(
        project_root / ARTIFACTS_DIR / TRACES_SUBDIR, TRACES_FILE_PREFIX
    )


def resolve_output_path(
    project_root: Path,
    user_value: str | None,
    *,
    default_dir: Path,
    prefix: str,
    ext: str = "json",
) -> Path:
    """Resolve a user-supplied ``--output`` value to a concrete file path.

    Semantics (shared by ``eval generate`` and ``eval dataset synthesize``):

      * ``user_value is None`` -> ``{default_dir}/{prefix}_<ts>.{ext}``;
        ``default_dir`` is created if missing.
      * ``user_value`` is an existing directory, or ends with ``/`` or
        ``os.sep`` -> a timestamped file is written inside it (the
        directory is created if missing).
      * Otherwise ``user_value`` is treated as a file path. Relative paths
        are anchored at ``project_root``.

    Returns:
        Resolved output file path.
    """
    if not user_value:
        return timestamped_artifact_path(default_dir, prefix, ext)
    has_trailing_sep = user_value.endswith(("/", os.sep))
    output_path = Path(user_value)
    if not output_path.is_absolute():
        output_path = project_root / output_path
    if has_trailing_sep:
        output_path.mkdir(parents=True, exist_ok=True)
    if output_path.is_dir():
        return output_path / f"{prefix}_{timestamp()}.{ext}"
    return output_path


def default_traces_dir(project_root: Path) -> Path:
    """Return the default stage-2 traces *directory* (not a file path).

    Form: ``{project_root}/{ARTIFACTS_DIR}/{TRACES_SUBDIR}``.

    Use this when callers want the directory to scan for existing trace
    files (e.g. ``eval grade`` resolving its default ``--traces``). To
    write a fresh timestamped trace file inside it, use
    ``default_traces_path`` instead.

    Does NOT create the directory.
    """
    return project_root / ARTIFACTS_DIR / TRACES_SUBDIR


def default_grade_results_dir(project_root: Path) -> Path:
    """Return the default stage-3 results directory.

    Form: ``{project_root}/{ARTIFACTS_DIR}/{GRADE_RESULTS_SUBDIR}``.

    Does NOT create the directory; ``eval grade`` does that itself when
    it knows it is going to write.
    """
    return project_root / ARTIFACTS_DIR / GRADE_RESULTS_SUBDIR
