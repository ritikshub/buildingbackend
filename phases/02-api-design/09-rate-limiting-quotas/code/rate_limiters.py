"""
Build It — three rate-limiting algorithms, and the boundary-burst bug that
separates them.

All three answer "has this key exceeded N ops per window?" but account for time
differently. To make the difference reproducible, every limiter takes an explicit
`now` (a fake clock) instead of reading the wall clock — so the demo is deterministic:

  * FixedWindow          — cheap, but allows up to 2x the limit across a boundary.
  * SlidingWindowCounter — two counters, weight the previous window; bounds the burst.
  * TokenBucket          — separates sustained rate from burst capacity.

Self-terminating: fires scripted bursts through each limiter, prints allow/deny
counts, exits 0.

Docs: phases/02-api-design/09-rate-limiting-quotas/docs/en.md
Spec: RFC 6585 (429), RFC 9110 (Retry-After). Token bucket is the classic traffic
      shaping model (AWS/Cloudflare edge limiters use these).

Run:
    python rate_limiters.py
"""

from __future__ import annotations


class FixedWindow:
    """One counter per aligned window. Simple, but bursty at boundaries."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window = limit, window
        self.counters: dict = {}

    def allow(self, key: str, now: float) -> bool:
        idx = int(now // self.window)
        count = self.counters.get((key, idx), 0)
        if count >= self.limit:
            return False
        self.counters[(key, idx)] = count + 1
        return True


class SlidingWindowCounter:
    """Weight the previous window's count by how much of it still overlaps 'now'."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window = limit, window
        self.counters: dict = {}

    def allow(self, key: str, now: float) -> bool:
        idx = int(now // self.window)
        elapsed = (now % self.window) / self.window          # 0..1 into current window
        current = self.counters.get((key, idx), 0)
        previous = self.counters.get((key, idx - 1), 0)
        estimate = previous * (1 - elapsed) + current        # smoothed rolling count
        if estimate >= self.limit:
            return False
        self.counters[(key, idx)] = current + 1
        return True


class TokenBucket:
    """Tokens drip in at `rate`/sec up to `capacity`; each request costs one.

    Lazy refill — no background timer; tokens are computed from elapsed time on each
    check. `capacity` is how much burst you forgive; `rate` is the long-run average.
    """

    def __init__(self, rate: float, capacity: float) -> None:
        self.rate, self.capacity = rate, capacity
        self.state: dict = {}   # key -> (tokens, last_seen)

    def allow(self, key: str, now: float, cost: float = 1.0) -> bool:
        tokens, last = self.state.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens >= cost:
            self.state[key] = (tokens - cost, now)
            return True
        self.state[key] = (tokens, now)
        return False


def fire(limiter, key: str, now: float, n: int) -> int:
    """Send n requests at instant `now`; return how many were allowed."""
    return sum(1 for _ in range(n) if limiter.allow(key, now))


def main() -> None:
    print("=== the boundary burst: 100 req just before, 100 just after t=60 ===")
    fw = FixedWindow(limit=100, window=60)
    a = fire(fw, "k", now=59.99, n=100)
    b = fire(fw, "k", now=60.01, n=100)
    print("  FixedWindow          allowed: {} + {} = {}  <-- ~2x the limit in ~0.02s".format(a, b, a + b))

    sw = SlidingWindowCounter(limit=100, window=60)
    a = fire(sw, "k", now=59.99, n=100)
    b = fire(sw, "k", now=60.01, n=100)
    print("  SlidingWindowCounter allowed: {} + {} = {}  <-- burst stays near the limit".format(a, b, a + b))

    print("\n=== token bucket: burst up to capacity, then throttle to rate ===")
    tb = TokenBucket(rate=10, capacity=10)
    burst = fire(tb, "k", now=0.0, n=15)
    print("  t=0.0  15 requests -> {} allowed (bucket held 10), 5 denied".format(burst))
    refill = fire(tb, "k", now=1.0, n=15)
    print("  t=1.0  15 requests -> {} allowed (1s refilled 10 tokens)".format(refill))
    trickle = fire(tb, "k", now=1.3, n=15)
    print("  t=1.3  15 requests -> {} allowed (0.3s refilled ~3 tokens)".format(trickle))


if __name__ == "__main__":
    main()
