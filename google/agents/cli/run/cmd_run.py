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

"""agents-cli run command — run agent with a single prompt."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import tempfile
import uuid
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

import click
import httpx
import requests
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    FilePart,
    FileWithBytes,
    FileWithUri,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TextPart,
    TransportProtocol,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

from google.agents.cli._project import (
    chdir_project_root,
    read_project_config,
    require_agent_directory,
)
from google.agents.cli.auth import get_access_token, get_id_token
from google.agents.cli.run._local_server import ensure_server, stop_server
from google.agents.cli.run._multimodal import (
    build_a2a_parts,
    build_adk_sse_parts,
    build_agent_runtime_message,
)

_AGENT_ENGINE_URL_FRAGMENT = "aiplatform.googleapis.com"
_REASONING_ENGINE_PATH = "reasoningEngines"


class _DispatchTarget(NamedTuple):
    service_url: str
    headers: dict
    mode: str
    app_name: str


def _resolve_dispatch_target(
    url: str | None,
    mode: str | None,
    app_name: str | None,
    custom_headers: tuple[str, ...],
) -> _DispatchTarget:
    """Resolve where and how to dispatch a query.

    Remote (``--url``): validates ``--mode`` first so missing flags don't
    surface as "no pyproject.toml". Reads the local project for
    ``app_name`` only when ``--app-name`` was not provided.

    Local: starts (or reuses) a background server and points at it.
    Always uses ADK SSE.
    """
    if url:
        if not mode:
            raise click.UsageError(
                "--mode is required when using --url. Choose from: a2a, adk"
            )
        if app_name:
            resolved = app_name
        else:
            chdir_project_root()
            cfg = read_project_config()
            require_agent_directory(cfg)
            resolved = cfg.agent_directory
        return _DispatchTarget(
            service_url=url,
            headers=_build_remote_headers(custom_headers, url),
            mode=mode,
            app_name=resolved,
        )

    chdir_project_root()
    cfg = read_project_config()
    require_agent_directory(cfg)
    port = ensure_server(Path.cwd(), cfg.agent_directory)
    return _DispatchTarget(
        service_url=f"http://localhost:{port}",
        headers={},
        mode="adk",
        app_name=app_name or cfg.agent_directory,
    )


def _handle_stop_server(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Eager callback for ``--stop-server``: stop and exit before argument parsing."""
    if not value:
        return
    chdir_project_root()
    if stop_server(Path.cwd()):
        ctx.exit(0)
    raise click.ClickException("No local server is running.")


def _parse_header(value: str) -> tuple[str, str]:
    """Parse a ``Key: Value`` header string."""
    if ":" not in value:
        raise click.BadParameter(
            f"Invalid header format (expected 'Key: Value'): {value}"
        )
    key, _, val = value.partition(":")
    return key.strip(), val.strip()


def _build_remote_headers(
    custom_headers: tuple[str, ...], url: str = ""
) -> dict[str, str]:
    """Build headers for remote requests.

    Auto-detects Google Cloud credentials unless the caller supplies
    an ``Authorization`` header via ``--header``.

    Uses an **access token** for Vertex AI / Agent Runtime URLs and an
    **identity token** (with the service URL as audience) for everything
    else (Cloud Run, GKE, etc.).
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    parsed = dict(_parse_header(h) for h in custom_headers)

    if "Authorization" not in parsed:
        try:
            if _is_agent_runtime_url(url):
                token = get_access_token()
            else:
                parsed_url = urlparse(url)
                audience = f"{parsed_url.scheme}://{parsed_url.netloc}"
                token = get_id_token(audience)
            headers["Authorization"] = f"Bearer {token}"
        except Exception as exc:
            click.echo(
                f"Warning: Could not obtain credentials: {exc}",
                err=True,
            )

    headers.update(parsed)
    return headers


@click.command("run")
@click.argument("message")
@click.option(
    "--url",
    default=None,
    help="URL of a remote agent to query.",
)
@click.option(
    "--mode",
    type=click.Choice(["a2a", "adk"], case_sensitive=False),
    default=None,
    help=(
        "Protocol for --url queries: 'a2a' or 'adk'. "
        "Required when using --url. Local runs always use ADK SSE."
    ),
)
@click.option(
    "--app-name",
    default=None,
    help=(
        "Agent name for remote ADK SSE / A2A endpoints. "
        "Defaults to the local project's agent_directory; "
        "specify to query a different agent or to run from outside a project."
    ),
)
@click.option(
    "--file",
    "-f",
    "files",
    multiple=True,
    type=click.Path(exists=True, readable=True),
    help="Attach a file (image, PDF, audio, video). Repeatable.",
)
@click.option(
    "--session-id",
    default=None,
    help="Resume an existing session/conversation context.",
)
@click.option(
    "--header",
    "-H",
    "custom_headers",
    multiple=True,
    help="Custom HTTP header (format: 'Key: Value'). Repeatable. Overrides auto-detected auth.",
)
@click.option(
    "--stop-server",
    "stop_server_flag",
    is_flag=True,
    default=False,
    is_eager=True,
    expose_value=False,
    callback=_handle_stop_server,
    help="Stop the local background server and exit.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Print full JSON event payloads.",
)
def cmd_run(
    message: str,
    url: str | None,
    mode: str | None,
    app_name: str | None,
    files: tuple[str, ...],
    session_id: str | None,
    custom_headers: tuple[str, ...],
    verbose: bool,
):
    """Run the agent with a single prompt (non-interactive).

    MESSAGE is the prompt to send to the agent.

    \b
    Run from your project directory to start a background
    ``adk api_server`` and query it automatically. The server
    is recycled after 30 min idle or with --stop-server.

    \b
    Use --url to query a deployed agent instead. Requires
    --mode to choose the protocol:

    \b
      a2a   A2A protocol
      adk   ADK SSE (/run_sse, or :streamQuery for Agent Runtime)

    \b
    Supports --file for multimodal input and --session-id for
    conversation continuity.
    """
    target = _resolve_dispatch_target(
        url=url,
        mode=mode,
        app_name=app_name,
        custom_headers=custom_headers,
    )
    if url:
        click.echo(f"Querying remote agent: {url} (mode: {target.mode})")

    try:
        _dispatch_query(
            service_url=target.service_url,
            message=message,
            files=files,
            headers=target.headers,
            mode=target.mode,
            app_name=target.app_name,
            session_id=session_id,
            verbose=verbose,
        )
    except (
        requests.ConnectionError,
        requests.Timeout,
        httpx.TransportError,
    ) as exc:
        if not url:
            raise
        raise click.ClickException(
            f"Could not reach remote agent at: {url}\n"
            f"  {exc}\n"
            "  Check that the URL is correct and the service is running."
        ) from exc


def _is_agent_runtime_url(url: str) -> bool:
    """Return ``True`` if *url* points to an Agent Runtime endpoint."""
    return _AGENT_ENGINE_URL_FRAGMENT in url and _REASONING_ENGINE_PATH in url


def _dispatch_query(
    service_url: str,
    message: str,
    files: tuple[str, ...],
    headers: dict,
    *,
    mode: str,
    app_name: str,
    session_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Route a query to the right protocol handler.

    Used by both local (``mode='adk'``, localhost ``service_url``,
    empty ``headers``) and remote (``mode`` from ``--mode``, deployed
    URL, auth headers) flows so the two paths can't drift.

    Modes:
      - ``a2a``: A2A protocol.  If the URL points to Agent Runtime,
        automatically constructs the ``/a2a`` sub-path; otherwise
        appends ``/a2a/{app_name}``.
      - ``adk``: ADK SSE.  Uses ``:streamQuery`` for Agent Runtime
        URLs, ``/run_sse`` for everything else.
    """
    if mode == "a2a":
        if _is_agent_runtime_url(service_url):
            a2a_base = service_url.replace("/v1/", "/v1beta1/") + "/a2a"
            card_url = f"{a2a_base}/v1/card"
        else:
            a2a_base = f"{service_url}/a2a/{app_name}"
            card_url = f"{a2a_base}{AGENT_CARD_WELL_KNOWN_PATH}"
        _query_a2a(
            card_url=card_url,
            parts=build_a2a_parts(message, files),
            headers=headers,
            url=a2a_base,
            session_id=session_id,
            verbose=verbose,
        )
    elif mode == "adk":
        if _is_agent_runtime_url(service_url):
            _query_agent_runtime_sse(
                service_url=service_url,
                message=build_agent_runtime_message(message, files),
                headers=headers,
                session_id=session_id,
                verbose=verbose,
            )
        else:
            _query_adk_sse(
                service_url=service_url,
                parts=build_adk_sse_parts(message, files),
                headers=headers,
                app_name=app_name,
                session_id=session_id,
                verbose=verbose,
            )


def _print_session_id(session_id: str | None) -> None:
    """Print session ID footer with resume hint."""
    if not session_id:
        return
    click.echo()
    click.secho(f"Session: {session_id} (resume with --session-id)", dim=True)


def _print_author_tag(author: str | None, last_author: str | None) -> str | None:
    """Print ``[author]:`` tag when author changes. Returns updated last_author."""
    if author and author != last_author:
        if last_author is not None:
            click.echo()
        click.echo(f"[{author}]: ", nl=False)
        return author
    return last_author


def _print_sse_event(event: dict, last_author: str | None, verbose: bool) -> str | None:
    """Process and print a single SSE/NDJSON event. Returns updated last_author."""
    author = event.get("author")
    last_author = _print_author_tag(author, last_author)
    content = event.get("content")
    if isinstance(content, dict):
        for part in content.get("parts", []):
            _print_sse_part(part)
    if verbose:
        click.echo()
        click.secho(json.dumps(event, indent=2), dim=True)
    return last_author


def _query_adk_sse(
    service_url: str,
    parts: list[dict],
    headers: dict,
    *,
    app_name: str,
    session_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Create a session and stream an SSE response from an ADK FastAPI agent."""
    if not session_id:
        # Create a new session
        session_url = f"{service_url}/apps/{app_name}/users/cli-user/sessions"
        session_resp = requests.post(session_url, headers=headers, json={}, timeout=30)
        if not session_resp.ok:
            hint = ""
            if session_resp.status_code in (404, 405):
                hint = "\n  If this is an A2A agent, try --mode a2a instead."
            raise click.ClickException(
                f"Failed to create session (HTTP {session_resp.status_code}):\n"
                f"  {session_resp.text}{hint}"
            )
        session_data = session_resp.json()
        session_id = session_data.get("id")

    # Print user message (text part only for display)
    user_text = " ".join(p.get("text", "") for p in parts if "text" in p).strip()
    if user_text:
        click.echo(f"[user]: {user_text}")

    # Send message via SSE
    run_url = f"{service_url}/run_sse"
    payload = {
        "app_name": app_name,
        "user_id": "cli-user",
        "session_id": session_id,
        "new_message": {
            "role": "user",
            "parts": parts,
        },
    }

    last_author = None
    with requests.post(
        run_url, headers=headers, json=payload, stream=True, timeout=120
    ) as resp:
        if not resp.ok:
            raise click.ClickException(
                f"Failed to run agent (HTTP {resp.status_code}):\n  {resp.text}"
            )
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[len("data: ") :]
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            last_author = _print_sse_event(event, last_author, verbose)

    click.echo()
    _print_session_id(session_id)


def _create_agent_runtime_session(
    service_url: str, headers: dict, user_id: str = "cli-user"
) -> str:
    resp = requests.post(
        f"{service_url}:query",
        headers=headers,
        json={
            "class_method": "async_create_session",
            "input": {"user_id": user_id},
        },
        timeout=30,
    )
    if not resp.ok:
        raise click.ClickException(
            f"Failed to create Agent Runtime session (HTTP {resp.status_code}):\n"
            f"  {resp.text}"
        )
    session_id = resp.json().get("output", {}).get("id")
    if not session_id:
        raise click.ClickException("Agent Runtime returned a session with no ID.")
    return session_id


def _query_agent_runtime_sse(
    service_url: str,
    message: str | dict,
    headers: dict,
    session_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Stream a query to an Agent Runtime via the ``:streamQuery`` HTTP endpoint.

    Uses the ``async_stream_query`` class method.  The response is
    newline-delimited JSON (one JSON object per line).  Creates a session
    via ``async_create_session`` when ``session_id`` is not provided.
    """
    if not session_id:
        session_id = _create_agent_runtime_session(service_url, headers)

    stream_url = f"{service_url}:streamQuery"

    input_payload: dict = {
        "user_id": "cli-user",
        "session_id": session_id,
        "message": message,
    }

    payload = {
        "class_method": "async_stream_query",
        "input": input_payload,
    }

    # Print user message
    user_text = (
        message
        if isinstance(message, str)
        else " ".join(
            p.get("text", "") for p in message.get("parts", []) if "text" in p
        ).strip()
    )
    if user_text:
        click.echo(f"[user]: {user_text}")

    with requests.post(
        stream_url, headers=headers, json=payload, stream=True, timeout=120
    ) as resp:
        if not resp.ok:
            hint = ""
            if resp.status_code in (400, 404, 405, 500):
                hint = (
                    "\n  This agent may not support the ADK :streamQuery API."
                    "\n  If this is an A2A agent, try --mode a2a instead."
                )
            raise click.ClickException(
                f"Failed to query Agent Runtime (HTTP {resp.status_code}):\n"
                f"  {resp.text}{hint}"
            )
        last_author = None
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            last_author = _print_sse_event(event, last_author, verbose)

    click.echo()
    _print_session_id(session_id)


def _query_a2a(
    card_url: str,
    parts: list[Part],
    headers: dict,
    url: str | None = None,
    session_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Fetch an A2A agent card and query the agent."""
    resp = httpx.get(card_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        hint = ""
        if resp.status_code in (404, 405):
            hint = "\n  If this is an ADK agent, try --mode adk instead."
        raise click.ClickException(
            f"Failed to fetch agent card (HTTP {resp.status_code}):\n  {resp.text}{hint}"
        )
    card = AgentCard(**resp.json())
    if url:
        card.url = url
    _query_a2a_with_card(card, parts, headers, session_id=session_id, verbose=verbose)


def _query_a2a_with_card(
    agent_card: AgentCard,
    parts: list[Part],
    headers: dict,
    *,
    session_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Query an A2A agent using a pre-fetched agent card."""
    asyncio.run(_query_a2a_async(agent_card, parts, headers, session_id, verbose))


async def _query_a2a_async(
    agent_card: AgentCard,
    parts: list[Part],
    headers: dict,
    session_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Async implementation — sends a message and prints the response."""
    agent_name = agent_card.name or "agent"

    # Print user message (text parts only for display)
    user_text = " ".join(
        p.root.text for p in parts if isinstance(p.root, TextPart) and p.root.text
    )
    if user_text:
        click.echo(f"[user]: {user_text}")

    async with httpx.AsyncClient(headers=headers, timeout=120) as client:
        factory = ClientFactory(
            ClientConfig(
                supported_transports=[
                    TransportProtocol.jsonrpc,
                    TransportProtocol.http_json,
                ],
                httpx_client=client,
            )
        )
        a2a_client = factory.create(agent_card)

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            parts=parts,
            context_id=session_id,
        )

        last_author = None
        response_session_id = None
        async for event in a2a_client.send_message(msg):
            if not isinstance(event, tuple):
                continue
            task, update = event

            # Capture session/context ID from the response
            if not response_session_id and task and task.context_id:
                response_session_id = task.context_id

            # Handle incremental artifact updates (streaming)
            if isinstance(update, TaskArtifactUpdateEvent):
                for part in update.artifact.parts:
                    last_author = _print_author_tag(agent_name, last_author)
                    _print_a2a_part(part)
            # Handle completed tasks with artifacts (non-streaming)
            elif update is None and task.artifacts:
                for artifact in task.artifacts:
                    for part in artifact.parts:
                        last_author = _print_author_tag(agent_name, last_author)
                        _print_a2a_part(part)

            if verbose:
                # Raw event dump (matches ADK/Agent Runtime output)
                raw: dict = {}
                if task:
                    raw["task"] = task.model_dump(exclude_none=True, mode="json")
                if update:
                    raw["update"] = update.model_dump(exclude_none=True, mode="json")
                if raw:
                    click.echo()
                    click.secho(json.dumps(raw, indent=2, default=str), dim=True)

    click.echo()
    _print_session_id(response_session_id)


def _print_a2a_part(part: Part) -> None:
    """Print an A2A response part to the terminal."""
    root = part.root
    if isinstance(root, TextPart) and root.text:
        click.echo(root.text, nl=False)
    elif isinstance(root, FilePart):
        file_data = root.file
        if isinstance(file_data, FileWithUri):
            click.echo(f"\n[file: {file_data.uri}]", nl=False)
        elif isinstance(file_data, FileWithBytes):
            # Save binary content to a temp file
            mime = file_data.mime_type or "application/octet-stream"
            ext = mimetypes.guess_extension(mime) or ""
            with tempfile.NamedTemporaryFile(
                suffix=ext, delete=False, prefix="agent_response_"
            ) as f:
                f.write(base64.b64decode(file_data.bytes))
                click.echo(f"\n[file saved: {f.name}]", nl=False)
    elif hasattr(root, "data") and root.data is not None:
        click.echo(f"\n{json.dumps(root.data, indent=2)}", nl=False)


def _print_sse_part(part: dict) -> None:
    """Print an ADK SSE response part to the terminal."""
    text = part.get("text")
    if text:
        click.echo(text, nl=False)
        return
    inline_data = part.get("inline_data")
    if inline_data:
        mime = inline_data.get("mime_type", "application/octet-stream")
        ext = mimetypes.guess_extension(mime) or ""
        with tempfile.NamedTemporaryFile(
            suffix=ext, delete=False, prefix="agent_response_"
        ) as f:
            f.write(base64.b64decode(inline_data["data"]))
            click.echo(f"\n[file saved: {f.name}]", nl=False)
        return
    file_data = part.get("file_data")
    if file_data:
        uri = file_data.get("file_uri")
        if uri:
            click.echo(f"\n[file: {uri}]", nl=False)
        return
    function_call = part.get("function_call")
    if function_call:
        name = function_call.get("name", "")
        args = function_call.get("args", {})
        click.echo(f"\n[tool_call: {name}({json.dumps(args)})]", nl=False)
        return
    function_response = part.get("function_response")
    if function_response:
        name = function_response.get("name", "")
        response = function_response.get("response", {})
        click.echo(f"\n[tool_response: {name} -> {json.dumps(response)}]", nl=False)
        return
