"""GENESIS Domain Error Hierarchy."""


class GenesisError(Exception):
    """Base exception for all GENESIS runtime errors."""


class QuotaExceededError(GenesisError):
    """Raised when an operation, entity touch, or loop depth limit is exceeded."""


class GRLValidationError(GenesisError):
    """Raised when GRL AST fails syntax, schema, or semantic validation."""


class GRLStructuralValidationError(GRLValidationError):
    """Raised when GRL AST violates structural constraints (loop depth, recursion)."""


class GRLExecutionError(GenesisError):
    """Raised when an unhandled error occurs during GRL rule execution."""


class PropertySchemaValidationError(GenesisError):
    """Raised when a property write violates type, bounds, or enum restrictions."""


class PropertyValueOutOfBoundsError(PropertySchemaValidationError):
    """Raised when a numerical property exceeds defined min/max bounds."""


class InvariantViolationError(GenesisError):
    """Raised when a simulation invariant is breached (e.g. negative resource balance)."""


class ResourceUnderflowError(InvariantViolationError):
    """Raised when a resource pool would drop below zero."""


class ResourceOverflowError(InvariantViolationError):
    """Raised when a resource pool exceeds maximum capacity."""


class ArithmeticRangeError(GenesisError):
    """Raised when an integer or fixed-point operation exceeds int64 bounds."""


class DivisionByZeroError(ArithmeticRangeError):
    """Raised when dividing or taking modulo by zero."""


class SerializationError(GenesisError):
    """Raised when canonical serialization or state deserialization fails."""


class SecurityViolationError(GenesisError):
    """Raised when an escape attempt, unauthorized path, or tampering is detected."""


class JournalTamperError(SecurityViolationError):
    """Raised when an append-only event journal segment or hash chain has been tampered with."""


class InternalRuntimeError(GenesisError):
    """Raised when an unexpected non-GENESIS exception occurs in the engine."""
