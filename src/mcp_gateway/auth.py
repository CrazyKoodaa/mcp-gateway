"""Authentication middleware for MCP Gateway."""

import hmac
import logging
import secrets

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# Security schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


class AuthConfig:
    """Authentication configuration."""

    def __init__(
        self,
        api_key: str | None = None,
        bearer_token: str | None = None,
        exclude_paths: list[str] | None = None,
    ):
        self.api_key = api_key
        self.bearer_token = bearer_token
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/openapi.json"]

    @property
    def is_enabled(self) -> bool:
        """Check if authentication is enabled."""
        return bool(self.api_key or self.bearer_token)

    def generate_api_key(self) -> str:
        """Generate a new secure API key."""
        return f"mg_{secrets.token_urlsafe(32)}"


class AuthMiddleware:
    """Authentication middleware for FastAPI."""

    def __init__(self, config: AuthConfig):
        self.config = config

    async def __call__(self, request: Request) -> str | None:
        """Authenticate request and return client identifier."""
        # Skip auth for excluded paths
        path = request.url.path
        if any(path.startswith(excluded) for excluded in self.config.exclude_paths):
            return "anonymous"

        if not self.config.is_enabled:
            return "anonymous"

        # Try API key header first
        api_key = request.headers.get("X-API-Key")
        if api_key:
            if self._verify_api_key(api_key):
                return f"apikey:{api_key[:8]}..."
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # Try Bearer token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix
            if self._verify_bearer_token(token):
                return f"bearer:{token[:8]}..."
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
            )

        # No valid credentials
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide X-API-Key header or Bearer token.",
        )

    def _verify_api_key(self, api_key: str) -> bool:
        """Verify API key using constant-time comparison."""
        if not self.config.api_key:
            return False
        return hmac.compare_digest(api_key, self.config.api_key)

    def _verify_bearer_token(self, token: str) -> bool:
        """Verify Bearer token using constant-time comparison."""
        if not self.config.bearer_token:
            return False
        return hmac.compare_digest(token, self.config.bearer_token)


async def verify_auth(
    request: Request,
    api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> str:
    """FastAPI dependency for authentication.

    Usage:
        @app.get("/protected")
        async def protected_route(client_id: str = Depends(verify_auth)):
            return {"client": client_id}
    """
    # Get middleware from app state
    auth_middleware = getattr(request.app.state, "auth_middleware", None)
    if not auth_middleware:
        return "anonymous"

    return await auth_middleware(request)


def setup_auth(app, config: AuthConfig) -> None:
    """Setup authentication for the FastAPI app."""
    if not config.is_enabled:
        logger.info("Authentication disabled")
        return

    auth_middleware = AuthMiddleware(config)
    app.state.auth_middleware = auth_middleware
    app.state.auth_config = config

    # Log auth mode (don't log the actual keys!)
    modes = []
    if config.api_key:
        modes.append("API-Key")
    if config.bearer_token:
        modes.append("Bearer")
    logger.info(f"Authentication enabled: {', '.join(modes)}")
    logger.info(f"Excluded paths: {config.exclude_paths}")
