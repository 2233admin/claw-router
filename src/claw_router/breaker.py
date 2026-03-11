"""Circuit breaker for upstream model endpoints."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown: int = 60):
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures: dict[str, int] = defaultdict(int)
        self.open_until: dict[str, float] = {}
        self.lock = Lock()

    def is_open(self, model: str) -> bool:
        with self.lock:
            if model in self.open_until:
                if time.time() < self.open_until[model]:
                    return True
                del self.open_until[model]
                self.failures[model] = 0
            return False

    def record_failure(self, model: str) -> None:
        with self.lock:
            self.failures[model] += 1
            if self.failures[model] >= self.threshold:
                self.open_until[model] = time.time() + self.cooldown
                logger.warning(f"[breaker] {model} OPEN for {self.cooldown}s")

    def record_success(self, model: str) -> None:
        with self.lock:
            self.failures[model] = 0
            self.open_until.pop(model, None)

    def status(self) -> dict[str, str]:
        """Return status of all known models."""
        with self.lock:
            now = time.time()
            all_models = set(self.failures.keys()) | set(self.open_until.keys())
            result = {}
            for m in sorted(all_models):
                if m in self.open_until and now < self.open_until[m]:
                    result[m] = "OPEN"
                else:
                    result[m] = "ok"
            return result
