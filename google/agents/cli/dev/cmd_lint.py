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

"""agents-cli lint command — run code linting."""

import click

from google.agents.cli._runner import run


@click.command("lint")
@click.option("--fix", is_flag=True, default=False, help="Auto-fix linting issues.")
@click.option("--mypy", is_flag=True, default=False, help="Also run mypy type checking.")
@click.option(
    "--skip-codespell",
    is_flag=True,
    default=False,
    help="Skip codespell spell checking.",
)
@click.option("--skip-ty", is_flag=True, default=False, help="Skip ty type checking.")
def cmd_lint(fix, mypy, skip_codespell, skip_ty):
    """Run code quality checks.

    \b
    Runs: uv run ruff check .
          uv run ruff format . --check
          uv run codespell (unless --skip-codespell)
          uv run ty check . (unless --skip-ty)
          uv run mypy . (if --mypy)
    """
    # Sync lint extras before running
    run(
        ["uv", "sync", "--dev", "--extra", "lint"],
        check_err_msg="Failed to sync lint dependencies",
    )

    if fix:
        run(
            ["uv", "run", "ruff", "check", ".", "--fix"],
            check_err_msg="Ruff check --fix failed",
        )
        run(
            ["uv", "run", "ruff", "format", "."],
            check_err_msg="Ruff format failed",
        )
    else:
        run(
            ["uv", "run", "ruff", "check", "."],
            check_err_msg="Ruff check failed",
        )
        run(
            ["uv", "run", "ruff", "format", ".", "--check"],
            check_err_msg="Ruff format check failed",
        )

    if not skip_codespell:
        run(
            ["uv", "run", "codespell"],
            check_err_msg="Codespell check failed",
        )

    if not skip_ty:
        run(
            ["uv", "run", "ty", "check", "."],
            check_err_msg="ty type check failed",
        )

    if mypy:
        run(
            ["uv", "run", "mypy", "."],
            check_err_msg="Mypy check failed",
        )
