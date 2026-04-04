"""Simple circuit breaker for external API calls.

Prevents cascading failures by temporarily stopping requests to
services that have failed multiple times in succession.
"""

import time
from dataclasses import dataclass, field


@dataclass
class CircuitBreaker:
    """Circuit breaker that opens after repeated failures.

    Args:
        name: Identifier for the external service.
        failure_threshold: Number of consecutive failures before opening.
        reset_timeout: Seconds to wait before allowing a retry (half-open).
    """

    name: str
    failure_threshold: int = 3
    reset_timeout: float = 60.0  # seconds
    _failures: int = field(default=0, init=False)
    _last_failure: float = field(default=0.0, init=False)
    _open: bool = field(default=False, init=False)

    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests).

        Automatically transitions to half-open after reset_timeout.
        """
        if self._open and (time.time() - self._last_failure) > self.reset_timeout:
            self._open = False
            self._failures = 0
        return self._open

    def record_failure(self, transient: bool = True) -> None:
        """Record a failed request. Opens circuit if threshold reached.

        Args:
            transient: If True (default), counts toward opening the circuit.
                If False (permanent/client error), logs but does not increment.
        """
        if not transient:
            return
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self.failure_threshold:
            self._open = True

    def record_success(self) -> None:
        """Record a successful request. Resets failure count and closes circuit."""
        self._failures = 0
        self._open = False
