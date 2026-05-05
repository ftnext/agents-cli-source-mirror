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

"""agents-cli eval run command — run agent evaluations."""

import glob as globmod
import os

import click

from google.agents.cli._project import (
    chdir_project_root,
    read_project_config,
    require_agent_directory,
)
from google.agents.cli._runner import run

_DEFAULT_EVALSET = "tests/eval/evalsets/basic.evalset.json"
_DEFAULT_CONFIG = "tests/eval/eval_config.json"


@click.command("run")
@click.option(
    "--evalset",
    default=None,
    help="Path to evalset JSON file.",
)
@click.option(
    "--config",
    default=None,
    help="Path to eval config JSON file.",
)
@click.option(
    "--all",
    "run_all",
    is_flag=True,
    default=False,
    help="Run all eval sets found in tests/eval/evalsets/.",
)
def cmd_eval(evalset, config, run_all):
    """Run agent evaluations.

    \b
    Runs: uv run adk eval ./{agent_dir} EVALSET --config_file_path CONFIG
    """
    chdir_project_root()
    cfg = read_project_config()
    require_agent_directory(cfg)
    agent_dir = f"./{cfg.agent_directory}"

    # Sync eval extras before running
    run(
        ["uv", "sync", "--dev", "--extra", "eval"],
        check_err_msg="Failed to sync eval dependencies",
    )

    if run_all:
        evalsets = sorted(globmod.glob("tests/eval/evalsets/*.evalset.json"))
        if not evalsets:
            raise click.ClickException("No evalset files found in tests/eval/evalsets/")
        # Auto-detect config file if not specified (same logic as single-evalset path)
        if not config and os.path.exists(_DEFAULT_CONFIG):
            config = _DEFAULT_CONFIG
        for es in evalsets:
            args = ["uv", "run", "adk", "eval", agent_dir, es]
            if config:
                args.extend(["--config_file_path", config])
            run(args, check_err_msg=f"Evaluation failed for {es}")
        return

    # Default to basic evalset if none specified
    if not evalset:
        if os.path.exists(_DEFAULT_EVALSET):
            evalset = _DEFAULT_EVALSET
        else:
            raise click.ClickException(
                "No --evalset specified and default "
                f"({_DEFAULT_EVALSET}) not found. "
                "Specify --evalset PATH or use --all."
            )

    # Auto-detect config file if not specified
    if not config and os.path.exists(_DEFAULT_CONFIG):
        config = _DEFAULT_CONFIG

    args = ["uv", "run", "adk", "eval", agent_dir, evalset]
    if config:
        args.extend(["--config_file_path", config])

    run(args, check_err_msg="Evaluation failed")
