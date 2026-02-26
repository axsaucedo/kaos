"""Custom Agent Example — Pydantic AI agent with custom tools and logic.

Demonstrates how to build a custom agent image that integrates with KAOS:
- Custom Pydantic AI tools defined in the image
- KAOS AgentServer provides health/ready/memory/A2A endpoints
- Deployed via Agent CRD with container.image override
"""

import random
from pydantic_ai import Agent as PydanticAgent
from pais.server import create_agent_server


def create_custom_agent():
    """Create a Pydantic AI agent with custom tools."""
    agent = PydanticAgent(
        model="test",  # Will be overridden by KAOS env vars
        instructions="You are a helpful math and utility assistant.",
        name="custom-agent",
        defer_model_check=True,
    )

    @agent.tool_plain
    def add(a: float, b: float) -> str:
        """Add two numbers together.

        Args:
            a: First number
            b: Second number

        Returns:
            The sum as a string
        """
        return str(a + b)

    @agent.tool_plain
    def multiply(a: float, b: float) -> str:
        """Multiply two numbers.

        Args:
            a: First number
            b: Second number

        Returns:
            The product as a string
        """
        return str(a * b)

    @agent.tool_plain
    def random_number(min_val: int = 1, max_val: int = 100) -> str:
        """Generate a random number in a range.

        Args:
            min_val: Minimum value (inclusive)
            max_val: Maximum value (inclusive)

        Returns:
            A random integer as a string
        """
        return str(random.randint(min_val, max_val))

    return agent


def get_app():
    """ASGI app factory for uvicorn — creates KAOS AgentServer with custom tools."""
    server = create_agent_server(custom_agent=create_custom_agent())
    return server.app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:get_app", factory=True, host="0.0.0.0", port=8000)
