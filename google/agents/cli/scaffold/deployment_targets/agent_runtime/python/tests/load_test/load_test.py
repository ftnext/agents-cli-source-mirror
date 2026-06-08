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

{%- if cookiecutter.is_a2a %}

import json
import logging
import os
import time

from locust import HttpUser, between, task

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize Vertex AI and load agent config
with open("deployment_metadata.json", encoding="utf-8") as f:
    remote_agent_runtime_id = json.load(f)["remote_agent_runtime_id"]

parts = remote_agent_runtime_id.split("/")
project_id = parts[1]
location = parts[3]
engine_id = parts[5]

# Convert remote agent engine ID to URLs
base_url = f"https://{location}-aiplatform.googleapis.com"
a2a_base_path = f"/v1beta1/projects/{project_id}/locations/{location}/reasoningEngines/{engine_id}/a2a/v1"

logger.info("Using remote agent engine ID: %s", remote_agent_runtime_id)
logger.info("Using base URL: %s", base_url)
logger.info("Using API base path: %s", a2a_base_path)


class SendMessageUser(HttpUser):
    """Simulates a user interacting with the send message API."""

    wait_time = between(1, 3)  # Wait 1-3 seconds between tasks
    host = base_url  # Set the base host URL for Locust

    @task
    def send_message_and_poll(self) -> None:
        """Simulates a chat interaction: sends a message and polls for completion."""
        headers = {"Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {os.environ['_AUTH_TOKEN']}"

        data = {
            "message": {
                "messageId": "msg-id",
                "content": [{"text": "Hello! What's the weather in New York?"}],
                "role": "ROLE_USER",
            }
        }

        e2e_start_time = time.time()
        with self.client.post(
            f"{a2a_base_path}/message:send",
            headers=headers,
            json=data,
            catch_response=True,
            name="/v1/message:send",
        ) as response:
            if response.status_code != 200:
                response.failure(
                    f"Send failed with status code: {response.status_code}"
                )
                return

            response.success()
            response_data = response.json()

            # Extract task ID
            try:
                task_id = response_data["task"]["id"]
            except (KeyError, TypeError) as e:
                logger.error(f"Failed to extract task ID: {e}")
                return

        # Poll for task completion
        max_polls = 20  # Maximum number of poll attempts
        poll_interval = 0.5  # Seconds between polls
        poll_count = 0

        while poll_count < max_polls:
            poll_count += 1
            time.sleep(poll_interval)

            with self.client.get(
                f"{a2a_base_path}/tasks/{task_id}",
                headers=headers,
                catch_response=True,
                name="/v1/tasks/{id}",
            ) as poll_response:
                if poll_response.status_code != 200:
                    poll_response.failure(
                        f"Poll failed with status code: {poll_response.status_code}"
                    )
                    return

                poll_data = poll_response.json()

                try:
                    task_state = poll_data["status"]["state"]
                except (KeyError, TypeError) as e:
                    logger.error(f"Failed to extract task state: {e}")
                    poll_response.failure(f"Invalid response format: {e}")
                    return

                # Check if task is complete
                if task_state in ["TASK_STATE_COMPLETED"]:
                    poll_response.success()

                    # Measure end-to-end time
                    e2e_duration = (time.time() - e2e_start_time) * 1000

                    # Fire custom event for end-to-end metrics
                    self.environment.events.request.fire(
                        request_type="E2E",
                        name="message:send_and_complete",
                        response_time=e2e_duration,
                        response_length=len(json.dumps(poll_data)),
                        response=poll_response,
                        context={"poll_count": poll_count},
                    )
                    return

                elif task_state in ["TASK_STATE_WORKING"]:
                    poll_response.success()

                else:
                    poll_response.failure(f"Task failed with state: {task_state}")
                    return

        # Timeout - task didn't complete in time
        self.environment.events.request.fire(
            request_type="TIMEOUT",
            name="message:timeout",
            response_time=(time.time() - e2e_start_time) * 1000,
            response_length=0,
            response=None,
            context={"poll_count": poll_count},
            exception=TimeoutError(f"Task did not complete after {max_polls} polls"),
        )
{%- else %}

import json
import logging
import os
import time

from locust import HttpUser, between, task

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize Vertex AI and load agent config
with open("deployment_metadata.json", encoding="utf-8") as f:
    remote_agent_runtime_id = json.load(f)["remote_agent_runtime_id"]

parts = remote_agent_runtime_id.split("/")
project_id = parts[1]
location = parts[3]
engine_id = parts[5]

# Convert remote agent engine ID to streaming URL.
base_url = f"https://{location}-aiplatform.googleapis.com"
url_path = f"/v1/projects/{project_id}/locations/{location}/reasoningEngines/{engine_id}:streamQuery"

logger.info("Using remote agent engine ID: %s", remote_agent_runtime_id)
logger.info("Using base URL: %s", base_url)
logger.info("Using URL path: %s", url_path)


class ChatStreamUser(HttpUser):
    """Simulates a user interacting with the chat stream API."""

    wait_time = between(1, 3)  # Wait 1-3 seconds between tasks
    host = base_url  # Set the base host URL for Locust

    @task
    def chat_stream(self) -> None:
        """Simulates a chat stream interaction."""
        headers = {"Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {os.environ['_AUTH_TOKEN']}"
        data = {
            "class_method": "async_stream_query",
            "input": {
                "user_id": "test",
                "message": "Hi!",
            },
        }
        start_time = time.time()
        with self.client.post(
            url_path,
            headers=headers,
            json=data,
            catch_response=True,
            name="/streamQuery async_stream_query",
            stream=True,
            params={"alt": "sse"},
        ) as response:
            if response.status_code == 200:
                events = []
                has_error = False
                for line in response.iter_lines():
                    if line:
                        line_str = line.decode("utf-8")
                        events.append(line_str)

                        if "429 Too Many Requests" in line_str:
                            self.environment.events.request.fire(
                                request_type="POST",
                                name=f"{url_path} rate_limited 429s",
                                response_time=0,
                                response_length=len(line),
                                response=response,
                                context={},
                            )

                        # Check for error responses in the JSON payload
                        try:
                            event_data = json.loads(line_str)
                            if isinstance(event_data, dict) and "code" in event_data:
                                # Flag any non-2xx codes as errors
                                if event_data["code"] >= 400:
                                    has_error = True
                                    error_msg = event_data.get(
                                        "message", "Unknown error"
                                    )
                                    response.failure(f"Error in response: {error_msg}")
                                    logger.error(
                                        "Received error response: code=%s, message=%s",
                                        event_data["code"],
                                        error_msg,
                                    )
                        except json.JSONDecodeError:
                            # If it's not valid JSON, continue processing
                            pass

                end_time = time.time()
                total_time = end_time - start_time

                # Only fire success event if no errors were found
                if not has_error:
                    self.environment.events.request.fire(
                        request_type="POST",
                        name="/streamQuery end",
                        response_time=total_time * 1000,  # Convert to milliseconds
                        response_length=len(events),
                        response=response,
                        context={},
                    )
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
{%- endif %}
