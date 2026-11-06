from functools import lru_cache

from fastapi import Request
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter

from app.core.config import settings
from app.core.errors import fail
from app.modules.identity.sessions import digest


@lru_cache(maxsize=4)
def limiter(url: str) -> MovingWindowRateLimiter:
    return MovingWindowRateLimiter(storage_from_string(url))


def enforce(request: Request, action: str, subject: str = "") -> None:
    cfg = settings()
    if cfg.auth_mode == "mock" and not cfg.rate_limit_url:
        return
    storage_url = cfg.rate_limit_url or cfg.redis_url
    try:
        engine = limiter(storage_url)
        rule = parse(cfg.invite_rate_limit if action == "invite" else cfg.auth_rate_limit)
        # The app does not trust caller-supplied X-Forwarded-For. A proxy-wide IP
        # bucket remains conservative; authenticated invites also bind tenant/member.
        key = subject or (request.client.host if request.client else "unknown")
        allowed = engine.hit(rule, "coroof", action, digest(key))
    except Exception:
        fail("rate_limit_unavailable", "访问保护暂不可用，请稍后再试", 503)
    if not allowed:
        fail("rate_limited", "请求较频繁，请稍后再试", 429)
