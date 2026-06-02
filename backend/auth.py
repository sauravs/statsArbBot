"""
Backend request authentication.

The session/JWT layer lives in the Next.js tier (cookie-based, see ui/lib/auth.ts
and ui/middleware.ts). Browsers never talk to FastAPI directly — every call is
proxied through `ui/app/api/proxy`, which verifies the JWT cookie and injects a
shared `X-API-Key` header. This module guards the FastAPI side by validating
that header, so the backend trusts only the proxy.

Usage:

    from auth import require_api_key

    @router.get("/api/system/health", dependencies=[Depends(require_api_key)])
    async def health(): ...
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

import config


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: reject requests without the shared proxy API key."""
    expected = config.API_KEY
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
