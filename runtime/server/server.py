"""
Agentic Agent Runtime Server using Google's ADK patterns.

This server loads configuration entirely from environment variables and
exposes a long-running HTTP API for agent operations including:
- Agent Card endpoint for A2A communication
- Agent invocation with tool access
- MCP tool integration
- Peer agent A2A communication
- Health check endpoints

Architecture:
- Uses environment variables for all configuration
- Integrates with MCP servers for tool definitions
- Calls model API (Ollama/vLLM) for reasoning
- Coordinates with peer agents via A2A protocol
"""

import os
import asyncio
import logging
import json
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import uvicorn

# Import local modules
from mcp_tools import MCPToolLoader
from a2a import A2AClient

# Configure logging
log_level = os.getenv("AGENT_LOG_LEVEL", "INFO")
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agentic Runtime",
    description="Agent Runtime Server for Agentic Kubernetes Operator",
    version="0.1.0"
)

# Global state
agent_config: Optional[Dict[str, Any]] = None
mcp_loader: Optional[MCPToolLoader] = None
a2a_client: Optional[A2AClient] = None


class AgentConfig(BaseModel):
    """Agent configuration from environment"""
    name: str
    description: str
    instructions: str
    model_api_url: str
    model_api_key: Optional[str] = None
    mcp_servers: Dict[str, str] = {}
    peer_agents: Dict[str, str] = {}


class TaskRequest(BaseModel):
    """Task invocation request"""
    task: str
    context: Optional[Dict[str, Any]] = None


class TaskResponse(BaseModel):
    """Task invocation response"""
    result: str
    reasoning: Optional[str] = None


def load_config() -> Dict[str, Any]:
    """Load configuration from environment variables"""
    # Parse MCP servers: MCP_SERVERS="server1,server2" + MCP_SERVER_<NAME>_URL=...
    mcp_servers = {}
    mcp_names = [s.strip() for s in os.getenv("MCP_SERVERS", "").split(",") if s.strip()]
    for name in mcp_names:
        env_key = f"MCP_SERVER_{name.upper()}_URL"
        url = os.getenv(env_key)
        if url:
            mcp_servers[name] = url
        else:
            logger.warning(f"MCP server {name} referenced but URL not found in {env_key}")

    # Parse peer agents: PEER_AGENTS="agent1,agent2" + PEER_AGENT_<NAME>_CARD_URL=...
    peer_agents = {}
    peer_names = [a.strip() for a in os.getenv("PEER_AGENTS", "").split(",") if a.strip()]
    for name in peer_names:
        env_key = f"PEER_AGENT_{name.upper()}_CARD_URL"
        url = os.getenv(env_key)
        if url:
            peer_agents[name] = url
        else:
            logger.warning(f"Peer agent {name} referenced but URL not found in {env_key}")

    return {
        "name": os.getenv("AGENT_NAME", "default-agent"),
        "description": os.getenv("AGENT_DESCRIPTION", "Default agent"),
        "instructions": os.getenv("AGENT_INSTRUCTIONS", "You are a helpful assistant."),
        "model_api_url": os.getenv("MODEL_API_URL", "http://localhost:8000"),
        "model_api_key": os.getenv("MODEL_API_KEY", ""),
        "mcp_servers": mcp_servers,
        "peer_agents": peer_agents,
        "endpoint": os.getenv("AGENT_ENDPOINT", "http://localhost:8000"),
    }


@app.on_event("startup")
async def startup_event():
    """Initialize agent on startup"""
    global agent_config, mcp_loader, a2a_client

    logger.info("Starting Agentic Runtime Server...")
    agent_config = load_config()

    logger.info(f"Agent: {agent_config['name']}")
    logger.info(f"Description: {agent_config['description']}")
    logger.info(f"Model API: {agent_config['model_api_url']}")

    if agent_config["mcp_servers"]:
        logger.info(f"MCP Servers: {list(agent_config['mcp_servers'].keys())}")
        mcp_loader = MCPToolLoader(agent_config["mcp_servers"])

    if agent_config["peer_agents"]:
        logger.info(f"Peer Agents: {list(agent_config['peer_agents'].keys())}")
        a2a_client = A2AClient(
            self_name=agent_config["name"],
            peer_agents=agent_config["peer_agents"]
        )

    logger.info("Agent initialized successfully")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "name": agent_config.get("name") if agent_config else "unknown"}


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint"""
    if not agent_config:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return {"status": "ready", "name": agent_config["name"]}


@app.get("/agent/card")
async def get_agent_card() -> Dict[str, Any]:
    """
    Agent Card endpoint for A2A communication.

    This endpoint is used by other agents to discover and communicate
    with this agent via A2A (Agent-to-Agent) protocol.
    """
    if not agent_config:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    # Get available tools from MCP servers
    tools = []
    if mcp_loader:
        try:
            tools = await mcp_loader.list_tools()
        except Exception as e:
            logger.error(f"Failed to load tools: {e}")

    return {
        "name": agent_config["name"],
        "description": agent_config["description"],
        "endpoint": agent_config["endpoint"],
        "tools": [{"name": t.get("name"), "description": t.get("description")} for t in tools],
        "capabilities": {
            "model_reasoning": True,
            "tool_use": len(tools) > 0,
            "agent_to_agent": len(agent_config["peer_agents"]) > 0,
        }
    }


async def call_model(prompt: str, system: Optional[str] = None) -> Optional[str]:
    """Call the model API with a prompt."""
    if not agent_config:
        return None

    try:
        headers = {}
        if agent_config["model_api_key"]:
            headers["Authorization"] = f"Bearer {agent_config['model_api_key']}"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Get model name from environment or default
        model_name = os.getenv("MODEL_NAME", "smollm2:135m")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{agent_config['model_api_url']}/chat/completions",
                json={
                    "model": model_name,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 1000,
                },
                headers=headers,
            )

            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                logger.error(f"Model API error: {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Error calling model: {e}")
        return None


async def execute_with_reasoning(task: str) -> str:
    """Execute a task with model reasoning and tool use."""
    if not agent_config:
        return "Error: Agent not configured"

    logger.info(f"Executing task: {task}")

    # Build system prompt with tools and instructions
    system_prompt = agent_config["instructions"]

    if mcp_loader:
        try:
            tools = await mcp_loader.list_tools()
            if tools:
                tool_descriptions = "\n".join([
                    f"- {t['name']}: {t['description']}"
                    for t in tools
                ])
                system_prompt += f"\n\nAvailable tools:\n{tool_descriptions}"
        except Exception as e:
            logger.error(f"Failed to list tools: {e}")

    # Add peer agent information if available
    if agent_config["peer_agents"] and a2a_client:
        peer_info = "\n\nYou can delegate tasks to peer agents:\n"
        for peer_name in agent_config["peer_agents"].keys():
            peer_info += f"- {peer_name}\n"
        system_prompt += peer_info

    logger.debug(f"System prompt:\n{system_prompt}")

    # Call model for reasoning
    logger.info("Calling model for reasoning...")
    response = await call_model(task, system_prompt)

    if response:
        logger.info(f"Model response received ({len(response)} chars)")
        return response
    else:
        return "Error: Failed to get response from model"


@app.post("/agent/invoke")
async def invoke_agent(request: TaskRequest) -> TaskResponse:
    """
    Invoke the agent with a task.

    The agent will:
    1. Load available tools from MCP servers
    2. Call the model with the task
    3. Optionally delegate to peer agents
    4. Return reasoning and result
    """
    if not agent_config:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = await execute_with_reasoning(request.task)
        return TaskResponse(result=result)
    except Exception as e:
        logger.error(f"Error invoking agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tools/execute")
async def execute_tool(request: Dict[str, Any]):
    """
    Execute a tool on this agent.

    Request format:
    {
        "tool_name": "math.add",
        "arguments": {"a": 2, "b": 3}
    }
    """
    if not agent_config or not mcp_loader:
        raise HTTPException(status_code=503, detail="Agent not initialized or no tools available")

    try:
        tool_name = request.get("tool_name")
        arguments = request.get("arguments", {})

        logger.info(f"Executing tool: {tool_name} with args {arguments}")

        result = await mcp_loader.execute_tool(tool_name, arguments)
        return {"result": result}
    except Exception as e:
        logger.error(f"Error executing tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics():
    """Get agent metrics (placeholder for monitoring integration)"""
    if not agent_config:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    return {
        "agent_name": agent_config["name"],
        "mcp_servers_count": len(agent_config["mcp_servers"]),
        "peer_agents_count": len(agent_config["peer_agents"]),
        "model_api_url": agent_config["model_api_url"],
    }


if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", os.getenv("PORT", "8000")))
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower())
