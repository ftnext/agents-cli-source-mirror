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

"""Helpers to show source file location in --help output."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import click


def _source_path(cmd: Any) -> str | None:
    """Resolve the absolute file path of a command's callback module."""
    cb = cmd.callback
    if cb is None:
        return None
    try:
        mod = importlib.import_module(cb.__module__)
        return inspect.getfile(mod)
    except Exception:
        return None


def patch_source_in_help(cmd: Any) -> None:
    """Recursively patch all commands to show source location in --help epilog."""
    original = cmd.format_epilog

    def _patched(ctx: click.Context, formatter: click.HelpFormatter) -> None:
        original(ctx, formatter)
        path = _source_path(cmd)
        if path:
            formatter.write("\n")
            formatter.write(f"Source: {path}\n")

    cmd.format_epilog = _patched

    if isinstance(cmd, click.Group):
        for sub in cmd.commands.values():
            patch_source_in_help(sub)
