"""Fault injection for inventory-service's DB access path.

Deliberately produces REAL failures, not faked status codes:
- "slow" / "query_timeout": a genuine SELECT pg_sleep(...) runs server-side.
- "connection_failed": a genuine TCP connection-refused error, via an engine
  pointed at a port nothing listens on.
- "pool_exhausted": holds a real connection open longer, so a *different*,
  concurrent request genuinely can't get one from the pool (pool_size=5,
  max_overflow=0 -- see ADR-0004) and times out for real.

Mode is in-memory and process-local (not persisted) -- restarting the
container resets it to "none". That's a feature for a learning exercise:
no risk of leaving chaos mode on by accident across a restart.
"""

import logging
import threading

from sqlalchemy import create_engine

logger = logging.getLogger("inventory-service.chaos")

_lock = threading.Lock()
_mode = "none"
_bad_engine = None

VALID_MODES = ("none", "slow", "query_timeout", "connection_failed", "pool_exhausted")


def get_mode() -> str:
    with _lock:
        return _mode


def set_mode(mode: str) -> str:
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown chaos mode '{mode}'. Valid modes: {', '.join(VALID_MODES)}")
    global _mode
    with _lock:
        _mode = mode
    logger.warning("Chaos mode changed to: %s", mode)
    return mode


def get_bad_engine(real_database_url: str):
    """A throwaway engine pointed at a port nothing listens on -- connecting
    to it raises a genuine OperationalError (connection refused), used by
    connection_failed mode. Memoized so repeated requests reuse one engine
    instead of leaking a new one per call."""
    global _bad_engine
    if _bad_engine is None:
        bad_url = real_database_url.replace(":5432/", ":5499/")
        # Pool is deliberately generous with a short pool_timeout. An earlier
        # version used pool_size=1 and left pool_timeout at SQLAlchemy's 30s
        # default; under concurrent load, requests queued for that single slot
        # (a 30s `connect` span was seen in a real drill trace) and surfaced
        # as pool_exhausted / query_timeout instead of connection_failed.
        # That made this chaos mode emit misleading secondary signals. The
        # pool must never be what fails here -- the refused connection is.
        _bad_engine = create_engine(
            bad_url,
            pool_size=20,
            max_overflow=0,
            pool_timeout=1,
            connect_args={"connect_timeout": 2},
        )
    return _bad_engine
