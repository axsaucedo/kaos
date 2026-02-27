from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pydantic-ai-server")
except PackageNotFoundError:
    __version__ = "dev"


def serve(agent, **kwargs):
    """Wrap a Pydantic AI agent with KAOS server capabilities and return an ASGI app.

    Args:
        agent: A pydantic_ai.Agent instance.
        **kwargs: Passed to create_agent_server().

    Returns:
        A FastAPI ASGI application.
    """
    from pais.server import create_agent_server

    return create_agent_server(custom_agent=agent, **kwargs).app
