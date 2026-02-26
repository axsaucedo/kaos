from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pai-server")
except PackageNotFoundError:
    __version__ = "dev"
