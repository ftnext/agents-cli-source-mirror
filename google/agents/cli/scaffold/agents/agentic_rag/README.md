# Agentic RAG

This agent provides a production-ready RAG setup with a data ingestion pipeline, enabling you to ingest, process, and embed custom data for improved retrieval and response quality. You can choose between different datastore options including Agent Platform Search and Agent Platform Vector Search depending on your specific needs.

The agent provides the infrastructure to create a Vertex AI Pipeline with your custom code. Because it's built on Vertex AI Pipelines, you benefit from features like scheduled runs, recurring executions, and on-demand triggers. For processing terabyte-scale data, we recommend combining Vertex AI Pipelines with data analytics tools like BigQuery or Dataflow.

![search agent demo](https://storage.googleapis.com/github-repo/generative-ai/sample-apps/e2e-gen-ai-app-starter-pack/starter-pack-search-pattern.gif)

## Architecture

The agent implements the following architecture:

![architecture diagram](https://storage.googleapis.com/github-repo/generative-ai/sample-apps/e2e-gen-ai-app-starter-pack/agentic_rag_agent_platform_search_architecture.png)

### Key Features

- **Built on Agent Development Kit (ADK):** ADK is a flexible, modular framework for developing and deploying AI agents. It integrates with the Google ecosystem and Gemini models, supporting various LLMs and open-source AI tools, enabling both simple and complex agent architectures.
- **Flexible Datastore Options:** Choose between Agent Platform Search or Agent Platform Vector Search for efficient data storage and retrieval based on your specific needs.
- **Automated Data Ingestion Pipeline:** Automates the process of ingesting data from input sources.
- **Custom Embeddings:** Generates embeddings using Vertex AI Embeddings and incorporates them into your data for enhanced semantic search.
- **Terraform Deployment:** Ingestion pipeline is instantiated with Terraform alongside the rest of the infrastructure.
- **CI/CD Integration:** Deployment of ingestion pipelines is added to the CD pipelines.
- **Customizable Code:** Easily adapt and customize the code to fit your specific application needs and data sources.
