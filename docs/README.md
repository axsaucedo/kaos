# KAOS Documentation

This documentation provides comprehensive coverage of the KAOS, a framework for deploying and managing AI agents with tool access and multi-agent coordination on Kubernetes.

## Documentation Structure

### Getting Started
- [Quick Start Guide](getting-started/quickstart.md) - Deploy your first agent in minutes
- [Installation](getting-started/installation.md) - Operator installation and prerequisites
- [Concepts](getting-started/concepts.md) - Core concepts and architecture overview

### Python Agent Framework
- [Overview](python-framework/overview.md) - Framework architecture and design principles
- [Agent](python-framework/agent.md) - Agent class, configuration, and lifecycle
- [Agentic Loop](python-framework/agentic-loop.md) - Reasoning loop, tool calling, delegation
- [Memory](python-framework/memory.md) - Session management and event storage
- [MCP Tools](python-framework/mcp-tools.md) - Model Context Protocol integration
- [ModelAPI](python-framework/model-api.md) - LLM client for OpenAI-compatible servers
- [Server](python-framework/server.md) - HTTP endpoints and deployment

### Kubernetes Operator
- [Overview](operator/overview.md) - Operator architecture and controllers
- [Agent CRD](operator/agent-crd.md) - Agent custom resource specification
- [ModelAPI CRD](operator/modelapi-crd.md) - Model API deployment modes
- [MCPServer CRD](operator/mcpserver-crd.md) - MCP tool server configuration
- [Gateway API](operator/gateway-api.md) - Gateway integration

### Tutorials
- [Simple Agent with Tools](tutorials/simple-agent-tools.md) - Basic agent with MCP tools
- [Multi-Agent Coordination](tutorials/multi-agent.md) - Coordinator and worker patterns
- [Custom MCP Tools](tutorials/custom-mcp-tools.md) - Creating dynamic tools

### Reference
- [Environment Variables](reference/environment-variables.md) - All configuration options
- [Troubleshooting](reference/troubleshooting.md) - Common issues and solutions

### Development
- [Testing](development/testing.md) - Running and writing tests

## Quick Links

| Resource | Description |
|----------|-------------|
| [GitHub](https://github.com/axsaucedo/kaos) | Source code repository |
| [Quick Start](getting-started/quickstart.md) | Get started in 5 minutes |
