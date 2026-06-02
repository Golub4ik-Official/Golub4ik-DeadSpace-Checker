import asyncio
import logging
import time
from collections import deque
from typing import Any, Dict


class StabilizedLoadOptimizer:
    def __init__(self, logger: logging.Logger, config: Any, initial_concurrency: int = 12) -> None:
        self.logger = logger
        self.cfg = config.api.load_optimizer

        self.high_latency_threshold = self.cfg.high_latency_threshold
        self.very_high_latency_threshold = self.cfg.very_high_latency_threshold
        self.low_latency_threshold = self.cfg.low_latency_threshold
        self.target_latency = self.cfg.target_latency

        self.max_concurrency = config.api.max_concurrent_requests
        self.min_concurrency = 3
        init_c = max(self.min_concurrency, min(initial_concurrency, self.max_concurrency))
        self.current_concurrency_level = init_c
        self.concurrency_semaphore = asyncio.Semaphore(self.current_concurrency_level)

        self.current_delay = 0.0
        self.max_delay = 15.0
        self.delay_increment = 0.2
        self.delay_decrement = 0.4

        self.latencies = deque(maxlen=60)
        self.recent_latencies = deque(maxlen=15)
        self.success_rate_tracker = deque(maxlen=50)
        self.average_latency = 0.0
        self.recent_average = 0.0
        self._ema_latency = 0.0
        self._ema_alpha = 0.2
        self.success_rate = 1.0
        self.error_requests = 0

        self.last_adjustment_time = 0
        self.min_adjustment_interval = self.cfg.min_adjustment_interval
        self.consecutive_reductions = 0
        self.consecutive_increases = 0
        self.max_consecutive_adjustments = self.cfg.max_consecutive_adjustments

        self.adjustment_history = deque(maxlen=20)
        self.lock = asyncio.Lock()

        self.adaptive_backoff_active = False
        self.original_concurrency = self.current_concurrency_level

        self.logger.info(
            f"StabilizedLoadOptimizer initialized: concurrency={self.current_concurrency_level}, "
            f"target_latency={self.target_latency}s"
        )

    def _update_metrics(self) -> None:
        if self.latencies:
            self.average_latency = sum(self.latencies) / len(self.latencies)
        if self.recent_latencies:
            self.recent_average = sum(self.recent_latencies) / len(self.recent_latencies)
        if self.success_rate_tracker:
            successful_requests = sum(self.success_rate_tracker)
            total_requests = len(self.success_rate_tracker)
            self.success_rate = successful_requests / total_requests if total_requests > 0 else 1.0
            self.error_requests = total_requests - successful_requests
        if self.latencies:
            last = self.latencies[-1]
            if self._ema_latency == 0.0:
                self._ema_latency = last
            else:
                self._ema_latency = (self._ema_alpha * last) + (1 - self._ema_alpha) * self._ema_latency

    async def record_latency(self, duration: float, success: bool) -> None:
        async with self.lock:
            effective_duration = duration if success else duration + self.target_latency * 2
            self.latencies.append(effective_duration)
            self.recent_latencies.append(effective_duration)
            self.success_rate_tracker.append(1 if success else 0)

            self._update_metrics()

            await self._check_adaptive_backoff()

            current_time = time.time()
            if current_time - self.last_adjustment_time < self.min_adjustment_interval:
                return

            if len(self.recent_latencies) < 5:
                return

            await self._consider_adjustment()

    async def _check_adaptive_backoff(self) -> None:
        latency_threshold = self.target_latency * 2.0

        if self.recent_average > latency_threshold and not self.adaptive_backoff_active:
            self.adaptive_backoff_active = True
            self.original_concurrency = self.current_concurrency_level
            new_concurrency = max(self.min_concurrency, self.current_concurrency_level // 2)

            if new_concurrency != self.current_concurrency_level:
                self.current_concurrency_level = new_concurrency
                self.concurrency_semaphore = asyncio.Semaphore(self.current_concurrency_level)
                self.logger.warning(
                    f"Adaptive backoff activated: reduced concurrency to {new_concurrency} "
                    f"(avg latency: {self.recent_average:.2f}s)"
                )

        elif self.recent_average < latency_threshold * 0.7 and self.adaptive_backoff_active:
            self.adaptive_backoff_active = False
            if self.original_concurrency != self.current_concurrency_level:
                self.current_concurrency_level = self.original_concurrency
                self.concurrency_semaphore = asyncio.Semaphore(self.current_concurrency_level)
                self.logger.info(
                    f"Adaptive backoff removed: restored concurrency to {self.original_concurrency} "
                    f"(avg latency: {self.recent_average:.2f}s)"
                )

    async def _consider_adjustment(self) -> None:
        adjustment_type = ""

        if self.success_rate < 0.8 and self.error_requests > 5:
            adjustment_type = "emergency_reduce"
        elif self.recent_average > self.very_high_latency_threshold:
            adjustment_type = "emergency_reduce"
        elif self.recent_average > self.target_latency * 1.75 and self.consecutive_reductions < self.max_consecutive_adjustments:
            adjustment_type = "reduce"
        elif self.recent_average < self.target_latency * 0.75 and self.success_rate > 0.95 and self.consecutive_increases < self.max_consecutive_adjustments:
            adjustment_type = "increase"
        else:
            self.consecutive_increases = 0
            self.consecutive_reductions = 0

        if adjustment_type:
            await self._make_adjustment(adjustment_type)
            self.last_adjustment_time = time.time()

    async def _make_adjustment(self, adjustment_type: str) -> None:
        old_concurrency = self.current_concurrency_level
        old_delay = self.current_delay

        if adjustment_type == "emergency_reduce":
            self.consecutive_reductions += 1
            self.consecutive_increases = 0
            if self.current_concurrency_level > self.min_concurrency:
                reduction = max(2, int(self.current_concurrency_level * 0.5))
                self.current_concurrency_level = max(self.min_concurrency, self.current_concurrency_level - reduction)
            self.current_delay = min(self.max_delay, self.current_delay + self.delay_increment * 2)
        elif adjustment_type == "reduce":
            self.consecutive_reductions += 1
            self.consecutive_increases = 0
            if self.current_concurrency_level > self.min_concurrency:
                reduction = 2 if self.current_concurrency_level > self.min_concurrency + 2 else 1
                self.current_concurrency_level = max(self.min_concurrency, self.current_concurrency_level - reduction)
            elif self.current_delay < self.max_delay:
                latency_ratio = self.recent_average / self.target_latency
                scaling_factor = max(1.0, min(latency_ratio, 3.0))
                increment = self.delay_increment * scaling_factor
                self.current_delay = min(self.max_delay, self.current_delay + increment)
        elif adjustment_type == "increase":
            self.consecutive_increases += 1
            self.consecutive_reductions = 0
            if self.current_delay > 0:
                self.current_delay = max(0.0, self.current_delay - self.delay_decrement)
            elif self.recent_average < self.target_latency * 0.6:
                self.current_concurrency_level = min(self.max_concurrency, self.current_concurrency_level + 1)

        if self.current_concurrency_level != old_concurrency:
            self.concurrency_semaphore = asyncio.Semaphore(self.current_concurrency_level)

        if self.current_concurrency_level != old_concurrency or self.current_delay != old_delay:
            log_msg = (
                f"Load adjustment ({adjustment_type}): "
                f"concurrency {old_concurrency}→{self.current_concurrency_level}, "
                f"delay {old_delay:.2f}s→{self.current_delay:.2f}s | "
                f"Recent Latency: {self.recent_average:.2f}s (Target: {self.target_latency}s), "
                f"Success Rate: {self.success_rate:.2%}"
            )
            self.logger.info(log_msg)
            self.adjustment_history.append(log_msg)

    async def wait_adaptive_delay(self) -> None:
        if self.current_delay > 0:
            await asyncio.sleep(self.current_delay)

    def get_current_stats(self) -> Dict[str, Any]:
        return {
            'concurrency_level': self.current_concurrency_level,
            'current_delay': round(self.current_delay, 2),
            'average_latency': round(self.average_latency, 2),
            'recent_average': round(self.recent_average, 2),
            'ema_latency': round(self._ema_latency, 2),
            'success_rate': round(self.success_rate, 3),
            'samples_collected': len(self.latencies),
            'adaptive_backoff_active': self.adaptive_backoff_active,
        }
