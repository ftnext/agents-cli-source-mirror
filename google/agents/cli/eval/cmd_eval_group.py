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

"""agents-cli eval command group."""

import click

from google.agents.cli._click import LazyGroup


@click.group("eval", cls=LazyGroup)
def eval_group():
    """Evaluate agents and compare results.

    \b
    Subcommands:
      run      Run agent evaluations
      compare  Compare two eval result JSON files
      optimize Optimize agent prompts using the GEPA framework.
    """


eval_group.add_lazy_command(
    "run",
    "google.agents.cli.eval.cmd_eval:cmd_eval",
    "Run agent evaluations.",
)
eval_group.add_lazy_command(
    "compare",
    "google.agents.cli.eval.cmd_compare:cmd_compare",
    "Compare two eval result JSON files.",
)
eval_group.add_lazy_command(
    "optimize",
    "google.agents.cli.eval.cmd_optimize:cmd_optimize",
    "Optimize agent prompts using the GEPA framework.",
)
