# YAAY Documentation

This documentation provides comprehensive coverage of the YAAY, a framework for deploying and managing AI agents with tool access and multi-agent coordination on Kubernetes.

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
- [Environment Variables](operator/environment-variables.md) - Configuration reference

### Tutorials
- [Simple Agent with Tools](tutorials/simple-agent-tools.md) - Basic agent with MCP tools
- [Multi-Agent Coordination](tutorials/multi-agent.md) - Coordinator and worker patterns
- [Hierarchical Agents](tutorials/hierarchical-agents.md) - Complex agent hierarchies
- [Custom MCP Tools](tutorials/custom-mcp-tools.md) - Creating dynamic tools

### Reference
- [API Reference](reference/api-reference.md) - Complete CRD field reference
- [Python API](reference/python-api.md) - Python class and method reference
- [Environment Variables](reference/environment-variables.md) - All configuration options
- [Troubleshooting](reference/troubleshooting.md) - Common issues and solutions

### Development
- [Testing](development/testing.md) - Running and writing tests
- [Contributing](development/contributing.md) - Development workflow
- [Architecture Decisions](development/architecture-decisions.md) - Design rationale

## Quick Links

| Resource | Description |
|----------|-------------|
| [Samples](../operator/config/samples/) | Ready-to-deploy example configurations |
| [CLAUDE.md](../CLAUDE.md) | Project memory and conventions |
| [REPORT.md](../REPORT.md) | Technical review and recommendations |
