"""Restrict the local service to the configured loopback authority."""
from __future__ import annotations
from urllib.parse import urlsplit


def allowed_host(value: str | None, port: int) -> bool:
    return value is not None and value.lower() in {
        f"127.0.0.1:{port}", f"localhost:{port}"
    }


def allowed_origin(value: str | None, port: int) -> bool:
    if value is None:
        return True
    try:
        origin = urlsplit(value)
        return (origin.scheme == "http" and not origin.username
                and not origin.password and not origin.path
                and not origin.query and not origin.fragment
                and allowed_host(origin.netloc, port))
    except ValueError:
        return False
