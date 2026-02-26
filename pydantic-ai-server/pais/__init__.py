from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pydantic-ai-server")
except PackageNotFoundError:
    __version__ = "dev"
