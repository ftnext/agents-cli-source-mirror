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

"""agents-cli eval compare command — compare two eval result JSON files."""

import json
from pathlib import Path

import click

from google.agents.cli._output import emit


def _diff(base: dict, cand: dict, prefix: str = "") -> dict:
    """Compute a recursive diff between two eval result dicts.

    Nested dicts are diffed recursively with dotted key paths.
    Numeric changes include a delta (e.g., "+0.07" or "-0.03").
    """
    differences = {}

    all_keys = set(base.keys()) | set(cand.keys())
    for key in sorted(all_keys):
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        base_val = base.get(key)
        cand_val = cand.get(key)

        if base_val == cand_val:
            continue

        # Recurse into nested dicts
        if isinstance(base_val, dict) and isinstance(cand_val, dict):
            nested = _diff(base_val, cand_val, prefix=full_key)
            differences.update(nested["differences"])
            continue

        entry = {"baseline": base_val, "candidate": cand_val}
        if isinstance(base_val, (int, float)) and isinstance(cand_val, (int, float)):
            delta = cand_val - base_val
            entry["delta"] = f"+{delta}" if delta >= 0 else str(delta)
        differences[full_key] = entry

    if prefix:
        return {"differences": differences}

    return {
        "baseline_keys": sorted(base.keys()),
        "candidate_keys": sorted(cand.keys()),
        "differences": differences,
        "changed_keys": sorted(differences.keys()),
        "unchanged_keys": sorted(k for k in all_keys if k not in differences),
    }


@click.command("compare")
@click.argument("baseline", type=click.Path(exists=True))
@click.argument("candidate", type=click.Path(exists=True))
def cmd_compare(baseline, candidate):
    """Compare two eval result JSON files.

    Reads BASELINE and CANDIDATE JSON files and produces a diff.
    No subprocess calls — purely in-process comparison.
    """
    base = json.loads(Path(baseline).read_text(encoding="utf-8"))
    cand = json.loads(Path(candidate).read_text(encoding="utf-8"))
    emit(_diff(base, cand))
