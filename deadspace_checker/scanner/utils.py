import functools
import random
import time


def cached(ttl=300):
    def decorator(func):
        cache = {}

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            cache_key = str(args[0]) if args else "default"
            if cache_key in cache:
                timestamp, value = cache[cache_key]
                if time.time() - timestamp < ttl:
                    return value
            result = await func(self, *args, **kwargs)
            cache[cache_key] = (time.time(), result)
            return result

        return wrapper

    return decorator


class CircuitBreaker:

    def __init__(self, failure_threshold=10, recovery_timeout=60, half_open_max_calls=5):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'
        self.half_open_calls = 0

    def call_succeeded(self):
        self.failure_count = 0
        if self.state == 'HALF_OPEN':
            self.state = 'CLOSED'
        self.half_open_calls = 0

    def call_failed(self):
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'

    def can_execute(self):
        if self.state == 'CLOSED':
            return True

        if self.state == 'OPEN':
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = 'HALF_OPEN'
                self.half_open_calls = 0
                return True
            return False

        if self.state == 'HALF_OPEN':
            if self.half_open_calls < self.half_open_max_calls:
                self.half_open_calls += 1
                return True
            return False

        return False


class ExponentialBackoff:

    def __init__(self, initial_delay=1.0, max_delay=60.0, multiplier=2.0, jitter=True):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self.current_delay = initial_delay

    def get_delay(self):
        delay = min(self.current_delay, self.max_delay)
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)

        self.current_delay *= self.multiplier
        return delay

    def reset(self):
        self.current_delay = self.initial_delay
