---
layout: home

hero:
  name: YAAY
  text: Yet Another Agentic System
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
  - icon: 🔧
    title: MCP Tools
    details: Integrate tools using the Model Context Protocol standard
  - icon: 🔗
    title: Multi-Agent Networks
    details: Build hierarchical agent systems with automatic delegation
  - icon: 🌐
    title: Gateway Integration
    details: Expose agents via Kubernetes Gateway API with automatic routing
  - icon: 📡
    title: OpenAI-Compatible
    details: All agents expose /v1/chat/completions endpoints
  - icon: 🔄
    title: Agentic Loop
    details: Built-in reasoning loop with tool calling and agent delegation
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
