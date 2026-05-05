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

"""Datastore types and descriptions for data ingestion."""

# Dictionary mapping datastore types to their descriptions
DATASTORES = {
    "agent_platform_search": {
        "name": "Agent Platform Search",
        "description": "Managed, serverless document store that enables Google-quality search and RAG for generative AI.",
    },
    "agent_platform_vector_search": {
        "name": "Agent Platform Vector Search",
        "description": "Scalable vector search engine for building search, recommendation systems, and generative AI applications. Based on ScaNN algorithm.",
    },
}

DATASTORE_TYPES = list(DATASTORES.keys())


def get_datastore_info(datastore_type: str) -> dict:
    """Get information about a datastore type.

    Args:
        datastore_type: The datastore type key

    Returns:
        Dictionary with datastore information

    Raises:
        ValueError: If the datastore type is not valid
    """
    if datastore_type not in DATASTORES:
        raise ValueError(f"Invalid datastore type: {datastore_type}")
    return DATASTORES[datastore_type]
