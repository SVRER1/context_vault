class ContextVaultError(Exception):
    """Base exception for Context Vault."""
    pass

class PathSecurityError(ContextVaultError):
    pass

class VaultBoundaryError(PathSecurityError):
    pass

class FileIntegrityError(ContextVaultError):
    pass

class ParseError(ContextVaultError):
    pass

class IndexError_(ContextVaultError):
    pass

class OllamaUnavailableError(ContextVaultError):
    pass

class OrganisationError(ContextVaultError):
    pass

class CollisionError(ContextVaultError):
    pass

class UndoError(ContextVaultError):
    pass

class LLMConnectionError(ContextVaultError):
    pass

