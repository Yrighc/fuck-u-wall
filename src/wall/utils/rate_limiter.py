"""TOTP 验证失败限流器（内存版）。

防御目标：防止对 6 位 TOTP 验证码的在线爆破。
策略：按客户端身份（IP）统计失败次数，达到阈值后锁定一段时间。

说明：
- 基于内存，仅适用于单进程部署（本应用使用 Flask 内置服务器，符合条件）。
- 身份键来自客户端 IP（CF-Connecting-IP / X-Forwarded-For / remote_addr）。
  请确保应用部署在 Cloudflare 代理或可信反向代理之后；直接暴露公网时，
  这些请求头可被伪造，限流可被绕过（见 app.py 中 _get_client_ip 的注释）。
"""

import threading
import time

# 内存安全阀：超过该数量的身份记录时整体清空，优先保证可用性
_MAX_TRACKED_IDENTITIES = 10_000


class LoginRateLimiter:
    """按身份统计失败次数并触发锁定的限流器。"""

    def __init__(self, max_failures: int = 5, lockout_seconds: int = 900) -> None:
        self.max_failures = max(1, max_failures)
        self.lockout_seconds = max(1, lockout_seconds)
        self._failures: dict[str, list[float]] = {}
        self._lockout_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_locked_out(self, identity: str) -> bool:
        """当前身份是否处于锁定状态。"""
        with self._lock:
            return self._lockout_until.get(identity, 0.0) > time.monotonic()

    def record_failure(self, identity: str) -> bool:
        """记录一次验证失败；达到阈值时触发锁定。

        返回 True 表示本次失败正好触发了锁定。
        """
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            recent = [
                t
                for t in self._failures.get(identity, [])
                if t > now - self.lockout_seconds
            ]
            recent.append(now)
            self._failures[identity] = recent
            if len(recent) >= self.max_failures:
                self._lockout_until[identity] = now + self.lockout_seconds
                # 锁定生效后清空计数，锁定结束即从零开始
                self._failures[identity] = []
                return True
            return False

    def record_success(self, identity: str) -> None:
        """验证成功后清零该身份的失败记录与锁定状态。"""
        with self._lock:
            self._failures.pop(identity, None)
            self._lockout_until.pop(identity, None)

    def recent_failures(self, identity: str) -> int:
        """当前窗口内该身份最近的失败次数（供日志使用）。"""
        with self._lock:
            now = time.monotonic()
            return sum(1 for t in self._failures.get(identity, []) if t > now - self.lockout_seconds)

    def _prune(self, now: float) -> None:
        """清理过期记录，防止字典无限增长。"""
        cutoff = now - self.lockout_seconds
        expired = [k for k, v in self._failures.items() if not v or max(v) <= cutoff]
        for k in expired:
            self._failures.pop(k, None)
        expired_lock = [k for k, v in self._lockout_until.items() if v <= now]
        for k in expired_lock:
            self._lockout_until.pop(k, None)
        if len(self._failures) + len(self._lockout_until) > _MAX_TRACKED_IDENTITIES:
            # 极端情况下（大量伪造 IP 洪泛）丢弃全部统计，优先保证服务可用
            self._failures.clear()
            self._lockout_until.clear()
