"""Serialised, rate-limited GET for the public Chess.com API.

Three problems are solved here rather than in the fetcher, because they are properties
of the network rather than of the task:

* **429 / Retry-After** — honoured, capped, with exponential backoff on 5xx.
* **certifi** — Windows Python ships no CA bundle, so urlopen fails with
  CERTIFICATE_VERIFY_FAILED on perfectly valid sites. If certifi is missing we say so
  loudly rather than quietly downgrading to an unverified connection.
* **A transient 404** — retried before it is believed, so a CDN hiccup does not cost a
  month of games.

Requests are paced with a minimum gap. Chess.com does not like concurrent requests to
the archive endpoints, and a naive sweep over 49 months is exactly the traffic pattern
that gets an IP blocked. Concurrency is deliberately out of scope.

Every failure returns ``None`` and logs one line. A partial run is a normal outcome,
not a crash.
"""

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from . import config

_last_request: Optional[float] = None


def _ssl_context() -> Optional[ssl.SSLContext]:
    """A verified TLS context, or ``None`` to fall back to the stdlib default."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        print(
            "  note: certifi is not installed; TLS may fail. pip install certifi",
            file=sys.stderr,
        )
        return None


SSL_CONTEXT = _ssl_context()


_log_enabled = True


def set_logging(enabled: bool) -> None:
    """Turn the run log off. The tests use this so they cannot write into the real one."""
    global _log_enabled
    _log_enabled = enabled


def log(message: str) -> None:
    """One line to stderr and to the run log. Never raises.

    ``config.LOG`` is read at call time, not captured at import, so a test can point it
    at a temp file before exercising the logging path.
    """
    print(f"{time.strftime('%H:%M:%S')} {message}", file=sys.stderr)
    if not _log_enabled:
        return
    try:
        log_path = config.LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def _pace(delay: float) -> None:
    global _last_request
    if _last_request is None or delay <= 0:
        _last_request = time.monotonic()
        return
    gap = delay - (time.monotonic() - _last_request)
    if gap > 0:
        time.sleep(gap)
    _last_request = time.monotonic()


def get(
    url: str,
    *,
    delay: float = config.DEFAULT_DELAY,
    timeout: int = config.DEFAULT_TIMEOUT,
    retries: int = config.DEFAULT_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[str]:
    """GET ``url`` as text, honouring Retry-After and backing off on errors."""
    backoff = 2.0
    for attempt in range(retries):
        _pace(delay)
        request = urllib.request.Request(
            url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout, context=SSL_CONTEXT
            ) as response:
                _last_request = time.monotonic()
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = min(int(exc.headers.get("Retry-After") or backoff), 60)
                log(f"  rate limited by {url}, waiting {wait}s")
                sleep(float(wait))
                backoff *= 2
                continue
            if exc.code >= 500:
                sleep(backoff)
                backoff *= 2
                continue
            # A 404 on a real archive URL is unusual, so it gets retried before we
            # accept it; a genuinely missing month fails every attempt and lands below.
            if exc.code == 404 and attempt < retries - 1:
                sleep(backoff)
                backoff *= 2
                continue
            log(f"  HTTP {exc.code} for {url}")
            return None
        except (urllib.error.URLError, OSError) as exc:
            if attempt == retries - 1:
                log(f"  network error for {url}: {exc}")
                return None
            sleep(backoff)
            backoff *= 2
    return None


def get_json(url: str, **kwargs: Any) -> Optional[Any]:
    """``get`` plus JSON parsing. Malformed JSON is a failure, not a crash.

    Returns ``None`` for anything unusable; ``get`` has already logged the specific
    cause (rate limit, HTTP status, network error, non-JSON body).
    """
    body = get(url, **kwargs)
    if body is None:
        return None
    try:
        return json.loads(body)
    except ValueError:
        log(f"  unexpected non-JSON response from {url}")
        return None