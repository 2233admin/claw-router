"""Tests for circuit breaker."""

import time
import pytest
from claw_router.breaker import CircuitBreaker


class TestCircuitBreaker:
    def test_initially_closed(self):
        b = CircuitBreaker()
        assert not b.is_open("model-a")

    def test_opens_after_threshold(self):
        b = CircuitBreaker(threshold=3, cooldown=60)
        for _ in range(3):
            b.record_failure("model-a")
        assert b.is_open("model-a")

    def test_stays_closed_below_threshold(self):
        b = CircuitBreaker(threshold=3)
        b.record_failure("model-a")
        b.record_failure("model-a")
        assert not b.is_open("model-a")

    def test_success_resets(self):
        b = CircuitBreaker(threshold=3)
        b.record_failure("model-a")
        b.record_failure("model-a")
        b.record_success("model-a")
        b.record_failure("model-a")
        assert not b.is_open("model-a")

    def test_cooldown_recovery(self):
        b = CircuitBreaker(threshold=1, cooldown=1)
        b.record_failure("model-a")
        assert b.is_open("model-a")
        # Manually expire the breaker
        b.open_until["model-a"] = time.time() - 1
        assert not b.is_open("model-a")

    def test_independent_models(self):
        b = CircuitBreaker(threshold=2)
        b.record_failure("a")
        b.record_failure("a")
        assert b.is_open("a")
        assert not b.is_open("b")

    def test_status(self):
        b = CircuitBreaker(threshold=1, cooldown=60)
        b.record_failure("x")
        b.record_success("y")
        s = b.status()
        assert "x" in s
