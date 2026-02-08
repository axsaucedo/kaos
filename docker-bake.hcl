// Docker Bake configuration for parallel image builds
// Used by CI to build all images concurrently

variable "REGISTRY" {
  default = "axsauze"
}

variable "OPERATOR_TAG" {
  default = "latest"
}

variable "AGENT_TAG" {
  default = "latest"
}

group "default" {
  targets = ["operator", "agent", "litellm", "mcp-python-string", "mcp-pctx"]
}

target "operator" {
  context = "./operator"
  dockerfile = "Dockerfile"
  tags = ["${REGISTRY}/kaos-operator:${OPERATOR_TAG}"]
}

target "agent" {
  context = "./data-plane/kaos-framework"
  dockerfile = "Dockerfile"
  tags = ["${REGISTRY}/kaos-agent:${AGENT_TAG}"]
}

target "litellm" {
  context = "./operator/hack"
  dockerfile = "Dockerfile.litellm"
  tags = ["ghcr.io/berriai/litellm:main-stable"]
}

target "mcp-python-string" {
  context = "./data-plane/mcp-servers/python-string"
  dockerfile = "Dockerfile"
  tags = ["${REGISTRY}/kaos-mcp-python-string:${AGENT_TAG}"]
}

target "mcp-pctx" {
  context = "./data-plane/mcp-servers/pctx"
  dockerfile = "Dockerfile"
  tags = ["${REGISTRY}/kaos-mcp-pctx:${AGENT_TAG}"]
}
