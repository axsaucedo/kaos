---
layout: home

hero:
  name: YAAY
  text: Yet Another Agentic System
  tagline: 🎉 The simplest way to deploy AI agents on Kubernetes
  actions:
    - theme: brand
      text: Get Started
      link: /getting-started/quickstart
    - theme: alt
      text: View on GitHub
      link: https://github.com/axsaucedo/yaay

features:
  - icon: 🤖
    title: Agent CRD
    details: Deploy AI agents as native Kubernetes resources with declarative YAML configuration
  - icon: 🔧
    title: MCP Tools
    details: Integrate tools using the Model Context Protocol standard for interoperability
  - icon: 🔗
    title: Multi-Agent Networks
    details: Build hierarchical agent systems with automatic discovery and delegation
  - icon: 🌐
    title: Gateway Integration
    details: Expose agents via Kubernetes Gateway API with automatic routing
  - icon: 📡
    title: OpenAI-Compatible
    details: All agents expose /v1/chat/completions endpoints for seamless integration
  - icon: 🔄
    title: Agentic Loop
    details: Built-in reasoning loop with tool calling and agent delegation
---

## Why YAAY?

**YAAY** makes deploying AI agents on Kubernetes as simple as writing YAML. No complex SDKs, no vendor lock-in—just define your agents, connect them to tools, and let Kubernetes handle the rest.

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
