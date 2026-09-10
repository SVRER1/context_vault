from contextvault.parsers.registry import ParserRegistry, create_default_registry
from contextvault.parsers.image import ImageOCRParser

_default_registry = create_default_registry()

def get_parser(extension: str):
    """Get the default parser for a given extension."""
    return _default_registry.get_parser(extension)

__all__ = ["get_parser", "ParserRegistry", "create_default_registry", "ImageOCRParser"]
