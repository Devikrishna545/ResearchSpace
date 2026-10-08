"""Compatibility import; route registration lives in api.v1.router."""

from app.api.v1.router import api_router

__all__ = ["api_router"]
