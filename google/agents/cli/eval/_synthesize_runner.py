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

"""Subprocess runner for ``agents-cli eval dataset synthesize``.

Loads the user's ADK agent and generates synthetic evaluation traces
by running the agent against a user simulator.

This file is added into the user's agent project by ``agents-cli eval
dataset synthesize`` and is only intended to be invoked by that command.
Do not modify it — edits will be lost.

``GOOGLE_CLOUD_PROJECT`` and ``GOOGLE_CLOUD_LOCATION`` are read from the
environment and consumed by ``vertexai.Client``.
"""

import asyncio
import datetime
import json
import os
import sys
import traceback
import uuid
from pathlib import Path

import vertexai
from google.adk.cli.utils.agent_loader import AgentLoader
from google.adk.evaluation.conversation_scenarios import (
    ConversationScenario,
)
from google.adk.evaluation.eval_case import (
    SessionInput as ADK_SessionInput,
)
from google.adk.evaluation.evaluation_generator import (
    EvaluationGenerator,
)
from google.adk.evaluation.simulation.llm_backed_user_simulator import (
    LlmBackedUserSimulator,
    LlmBackedUserSimulatorConfig,
)
from google.genai import types as genai_types
from vertexai import types


def _ensure_eval_compatible(agent):
    """Inject an empty ``tools`` list where the agent lacks one.

    The Vertex eval SDK's ``AgentConfig.from_agent`` iterates ``agent.tools``
    unconditionally, but workflow agents (``BaseAgent`` subclasses such as
    ``SequentialAgent``/``ParallelAgent``/``LoopAgent``) have no ``tools``
    field, so introspection raises ``AttributeError``. Recurses through
    ``sub_agents`` because the SDK builds the agent map over the whole tree,
    and a sub-agent may itself be a workflow agent.

    See https://github.com/googleapis/python-aiplatform/issues/6865.
    """
    if not hasattr(agent, "tools"):
        object.__setattr__(agent, "tools", [])
    for sub_agent in getattr(agent, "sub_agents", None) or []:
        _ensure_eval_compatible(sub_agent)
    return agent


def _final_response_from_invocations(invocations):
    """Extract the final agent text response across all invocations.

    Walks invocations in reverse to find the most recent ``final_response``
    that contains a non-empty ``text`` part. Returns a ``ResponseCandidate``
    wrapping a ``Content`` object suitable for ``EvalCase.responses[0]``,
    or ``None`` if no text was found.

    Ensures custom metric handlers (LLMMetric and custom_function) can
    read ``instance.response`` without erroring on missing response content.
    """
    for invocation in reversed(invocations):
        final = getattr(invocation, "final_response", None)
        if not final:
            continue
        parts = getattr(final, "parts", None) or []
        texts = [getattr(p, "text", None) for p in parts]
        texts = [t for t in texts if t]
        if texts:
            return types.ResponseCandidate(
                response=genai_types.Content(
                    role=getattr(final, "role", None) or "model",
                    parts=[genai_types.Part(text="".join(texts))],
                )
            )
    return None


def _invocations_to_turns(invocations):
    """Converts ADK ``Invocation`` objects to trace turn dicts."""
    turns = []
    for i, invocation in enumerate(invocations):
        events = []
        ts = datetime.datetime.fromtimestamp(
            invocation.creation_timestamp, tz=datetime.UTC
        )

        if invocation.user_content:
            events.append(
                {
                    "author": "user",
                    "content": invocation.user_content.model_dump(
                        mode="json", exclude_none=True
                    ),
                    "event_time": ts,
                }
            )

        intermediate = invocation.intermediate_data
        if intermediate is not None:
            inv_events = getattr(intermediate, "invocation_events", None)
            tool_uses = getattr(intermediate, "tool_uses", None)
            if inv_events:
                for ie in inv_events:
                    events.append(
                        {
                            "author": ie.author,
                            "content": (
                                ie.content.model_dump(mode="json", exclude_none=True)
                                if ie.content
                                else None
                            ),
                            "event_time": ts,
                        }
                    )
            elif tool_uses:
                for tool_call in tool_uses:
                    events.append(
                        {
                            "author": "tool_call",
                            "content": tool_call.model_dump(
                                mode="json", exclude_none=True
                            ),
                            "event_time": ts,
                        }
                    )

        if invocation.final_response:
            events.append(
                {
                    "author": "agent",
                    "content": invocation.final_response.model_dump(
                        mode="json", exclude_none=True
                    ),
                    "event_time": ts,
                }
            )

        turns.append(
            {
                "turn_index": i,
                "turn_id": invocation.invocation_id or str(uuid.uuid4()),
                "events": events,
            }
        )
    return turns


def main():
    agent_dir = sys.argv[1]
    config_json = sys.argv[2]
    output_path = sys.argv[3]
    max_turns = int(sys.argv[4])

    config = json.loads(config_json)

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", None)
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", None)

    resolved = Path(agent_dir).resolve()
    loader = AgentLoader(agents_dir=str(resolved.parent))
    loaded = loader.load_agent(resolved.name)

    try:
        from google.adk.apps import App

        if isinstance(loaded, App):
            agent = loaded.root_agent
        else:
            agent = loaded
    except ImportError:
        agent = loaded

    agent = _ensure_eval_compatible(agent)
    agent_info = types.evals.AgentInfo.load_from_agent(agent=agent)

    client = vertexai.Client(project=project, location=location)
    print(
        f"Calling Vertex AI generate_conversation_scenarios "
        f"(project={project}, location={location})...",
        flush=True,
    )
    eval_dataset = client.evals.generate_conversation_scenarios(
        agent_info=agent_info,
        config=config,
        allow_cross_region_model=True,
    )
    n_cases = len(eval_dataset.eval_cases or [])
    print(f"Got {n_cases} scenarios; running user simulations...", flush=True)

    async def _run_simulation():
        eval_cases = []
        failures = 0
        for case in eval_dataset.eval_cases or []:
            scenario = case.user_scenario
            if not scenario:
                continue
            conv = ConversationScenario(
                starting_prompt=scenario.starting_prompt,
                conversation_plan=scenario.conversation_plan,
            )
            sim_cfg = LlmBackedUserSimulatorConfig(
                max_allowed_invocations=max_turns,
            )
            sim = LlmBackedUserSimulator(
                conversation_scenario=conv,
                config=sim_cfg,
            )
            try:
                invocations = await (
                    EvaluationGenerator._generate_inferences_from_root_agent(
                        root_agent=agent,
                        user_simulator=sim,
                        reset_func=getattr(agent, "reset_data", None),
                        initial_session=ADK_SessionInput(
                            app_name="user_simulation_app",
                            user_id="user_simulation_default_user",
                            state={},
                        ),
                    )
                )
            except Exception as exc:
                failures += 1
                print(
                    f"Warning: simulation failed for scenario: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                traceback.print_exc(file=sys.stderr)
                invocations = []

            turns = _invocations_to_turns(invocations)
            agent_data = types.evals.AgentData(
                turns=[types.evals.ConversationTurn(**t) for t in turns]
            )
            existing_id = getattr(case, "eval_case_id", None)
            final_response = _final_response_from_invocations(invocations)
            responses = [final_response] if final_response is not None else None
            eval_case = types.EvalCase(
                eval_case_id=existing_id or str(uuid.uuid4()),
                user_scenario=types.evals.UserScenario(
                    starting_prompt=scenario.starting_prompt,
                    conversation_plan=scenario.conversation_plan,
                ),
                agent_data=agent_data,
                responses=responses,
            )
            eval_cases.append(eval_case)
        return eval_cases, failures

    eval_cases, failures = asyncio.run(_run_simulation())

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output_dataset = types.EvaluationDataset(eval_cases=eval_cases)
    out_path.write_text(
        output_dataset.model_dump_json(
            indent=2,
            exclude_none=True,
            by_alias=False,
        ),
        encoding="utf-8",
    )
    if failures:
        print(
            f"Warning: {failures}/{n_cases} scenarios failed during "
            "simulation; their agent_data will have empty turns.",
            file=sys.stderr,
            flush=True,
        )


if __name__ == "__main__":
    main()
    os._exit(0)
