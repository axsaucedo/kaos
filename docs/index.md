---
layout: home

hero:
  name: KAOS
  text: K8s Agent Orchestration System
  tagline: Deploy, manage, and orchestrate AI agents on Kubernetes
  actions:
    - theme: brand
      text: Get Started
      link: /getting-started/quickstart
    - theme: alt
      text: View on GitHub
      link: https://github.com/axsaucedo/kaos

features:
  - icon: 🤖
    title: Agent CRD
    details: Deploy AI agents as Kubernetes resources with declarative configuration
    link: /operator/agent-crd
  - icon: 🔧
    title: MCP Tools
    details: Integrate tools using the Model Context Protocol standard
    link: /python-framework/mcp-tools
  - icon: 🔗
    title: Multi-Agent Networks
    details: Build hierarchical agent systems with automatic delegation
    link: /tutorials/multi-agent
  - icon: 🌐
    title: Gateway Integration
    details: Expose agents via Kubernetes Gateway API with automatic routing
    link: /operator/gateway-api
  - icon: 📡
    title: OpenAI-Compatible
    details: All agents expose /v1/chat/completions endpoints
    link: /python-framework/server
  - icon: 🔄
    title: Agentic Loop
    details: Built-in reasoning loop with tool calling and agent delegation
    link: /python-framework/agentic-loop
---

## Quick Example

```yaml
apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: assistant
spec:
  modelAPI: ollama
  mcpServers:
    - echo-tools
  config:
    description: "Helpful AI assistant"
    instructions: "You are a helpful assistant."
```
