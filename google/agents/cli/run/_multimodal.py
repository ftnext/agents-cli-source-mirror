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

"""Multimodal helpers for building message parts from files."""

import base64
import mimetypes
from pathlib import Path

import click
from a2a.types import FilePart, FileWithBytes, Part, TextPart

# Warn when a file exceeds this size (bytes).
_SIZE_WARNING_THRESHOLD = 20 * 1024 * 1024  # 20 MB


def build_a2a_parts(message: str, files: tuple[str, ...] = ()) -> list[Part]:
    """Build A2A ``Part`` objects from a text message and optional file paths.

    Args:
        message: The text message.
        files: Zero or more file paths to attach.

    Returns:
        List of ``Part`` objects ready for an A2A ``Message``.
    """
    parts: list[Part] = []
    if message:
        parts.append(Part(root=TextPart(text=message)))

    for file_path in files:
        data, mime_type = _read_and_encode(file_path)
        parts.append(
            Part(root=FilePart(file=FileWithBytes(bytes=data, mime_type=mime_type)))
        )

    return parts


def build_adk_sse_parts(message: str, files: tuple[str, ...] = ()) -> list[dict]:
    """Build ADK SSE dict parts from a text message and optional file paths.

    Args:
        message: The text message.
        files: Zero or more file paths to attach.

    Returns:
        List of dicts suitable for the ``new_message.parts`` field in
        the ``/run_sse`` payload.
    """
    parts: list[dict] = []
    if message:
        parts.append({"text": message})

    for file_path in files:
        data, mime_type = _read_and_encode(file_path)
        parts.append({"inline_data": {"data": data, "mime_type": mime_type}})

    return parts


def build_agent_runtime_message(message: str, files: tuple[str, ...] = ()) -> str | dict:
    """Build a message for Agent Runtime streaming queries.

    Returns a plain string for text-only messages or a Content dict
    (with ``parts``) for multimodal input.  The dict form is needed
    because the dynamic method wrapping serialises kwargs as JSON, so
    ``types.Part`` objects cannot be used directly.

    Args:
        message: The text message.
        files: Zero or more file paths (local or ``gs://`` URIs).

    Returns:
        A string or ``{"parts": [...]}`` dict.
    """
    if not files:
        return message

    parts: list[dict] = [{"text": message}]
    for file_path in files:
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        if file_path.startswith("gs://"):
            parts.append({"file_data": {"file_uri": file_path, "mime_type": mime}})
        else:
            data, mime = _read_and_encode(file_path)
            parts.append({"inline_data": {"data": data, "mime_type": mime}})
    return {"parts": parts}


def _read_and_encode(file_path: str) -> tuple[str, str]:
    """Read a file, base64-encode it, and detect its MIME type.

    Returns:
        Tuple of (base64_encoded_data, mime_type).
    """
    path = Path(file_path)
    size = path.stat().st_size
    if size > _SIZE_WARNING_THRESHOLD:
        click.echo(
            f"Warning: {path.name} is {size / 1024 / 1024:.1f} MB — "
            "large files may cause slow uploads or timeouts.",
            err=True,
        )

    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return encoded, mime_type
