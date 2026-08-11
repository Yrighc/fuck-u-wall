"""LoginRateLimiter 单元测试"""
import time
from unittest.mock import patch

from wall.utils.rate_limiter import LoginRateLimiter


def test_allows_attempts_below_threshold() -> None:
    limiter = LoginRateLimiter(max_failures=3, lockout_seconds=60)
    assert not limiter.is_locked_out("1.2.3.4")
    assert not limiter.record_failure("1.2.3.4")
    assert not limiter.record_failure("1.2.3.4")
    assert not limiter.is_locked_out("1.2.3.4")
    # 第三次失败触发锁定
    assert limiter.record_failure("1.2.3.4") is True
    assert limiter.is_locked_out("1.2.3.4")


def test_other_identities_unaffected() -> None:
    limiter = LoginRateLimiter(max_failures=1, lockout_seconds=60)
    assert limiter.record_failure("a")
    assert limiter.is_locked_out("a")
    # b 不受 a 的锁定影响，直到自己失败才锁定
    assert not limiter.is_locked_out("b")
    assert limiter.record_failure("b")
    assert limiter.is_locked_out("b")


def test_success_resets_failures_and_lockout() -> None:
    limiter = LoginRateLimiter(max_failures=2, lockout_seconds=60)
    limiter.record_failure("1.2.3.4")
    limiter.record_success("1.2.3.4")
    # 成功清零后，同样的失败次数不再触发锁定
    assert not limiter.record_failure("1.2.3.4")
    assert not limiter.is_locked_out("1.2.3.4")
    # 锁定期内成功也能解除锁定
    limiter.record_failure("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert limiter.is_locked_out("1.2.3.4")
    limiter.record_success("1.2.3.4")
    assert not limiter.is_locked_out("1.2.3.4")


def test_lockout_expires_after_duration() -> None:
    limiter = LoginRateLimiter(max_failures=1, lockout_seconds=60)
    now = time.monotonic()
    with patch(
        "wall.utils.rate_limiter.time.monotonic",
        side_effect=[now, now, now + 61],
    ):
        assert limiter.record_failure("1.2.3.4")
        assert limiter.is_locked_out("1.2.3.4")
        # 锁定时间过后自动解除
        assert not limiter.is_locked_out("1.2.3.4")


def test_old_failures_expire_outside_window() -> None:
    limiter = LoginRateLimiter(max_failures=2, lockout_seconds=60)
    now = time.monotonic()
    with patch(
        "wall.utils.rate_limiter.time.monotonic",
        side_effect=[now, now + 61, now + 62],
    ):
        limiter.record_failure("1.2.3.4")  # t0
        # 61 秒后第一次失败已过期，再来一次失败不会触发锁定
        assert not limiter.record_failure("1.2.3.4")  # t0+61
        assert not limiter.is_locked_out("1.2.3.4")  # t0+62


def test_identity_count_is_bounded() -> None:
    limiter = LoginRateLimiter(max_failures=1, lockout_seconds=60)
    # 超过内存安全阀后整体清空：早期身份不再处于锁定状态，服务可用
    for i in range(10_002):
        limiter.record_failure(f"ip-{i}")
    assert not limiter.is_locked_out("ip-0")
