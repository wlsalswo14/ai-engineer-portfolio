class PrimusError(RuntimeError):
    """Base fail-closed Primus error."""


class ContractError(PrimusError):
    """A frozen contract or schema is invalid."""


class IntegrityError(PrimusError):
    """A digest, immutable object, receipt, or pointer is inconsistent."""


class LifecycleError(PrimusError):
    """A requested state transition is not permitted."""


class EvaluationError(PrimusError):
    """A domain evaluation failed closed."""


class BackendError(PrimusError):
    """A model backend call failed."""


class QuotaUnavailable(BackendError):
    """All configured subscription homes rejected the call for quota."""
