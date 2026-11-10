from __future__ import annotations


class DomainError(Exception):
    """A request that conflicts with current business state (HTTP 409)."""


class InvalidTransition(DomainError):
    def __init__(self, kind: str, current: str, target: str) -> None:
        super().__init__(f"{kind} cannot move from {current} to {target}")
        self.kind = kind
        self.current = current
        self.target = target


class ImmutableRecordError(DomainError):
    """Attempt to change original/extracted values or append-only records."""


class ValidationFailed(Exception):
    """Input is well-formed but semantically invalid (HTTP 422)."""


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass
