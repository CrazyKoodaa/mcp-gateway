"""Main entry point for MCP Gateway with explicit dependency injection."""

from __future__ import annotations

# Suppress async generator warnings at import time
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited.*")
warnings.filterwarnings("ignore", message=".*async generator.*")
warnings.filterwarnings("ignore", message=".*unclosed.*")

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from .admin import ConfigManager
from .auth import AuthConfig, AuthMiddleware
from .backends import BackendManager
from .circuit_breaker import CircuitBreakerRegistry
from .config import GatewayConfig, load_config
from .hot_reload import HotReloadManager

# Get structured logger
from .logging_config import get_logger, setup_structured_logging
from .metrics import MetricsCollector
from .server import McpGatewayServer, ServerDependencies
from .access_control import AccessControlManager
from .services import AuditService, ConfigApprovalService, PathSecurityService
from .supervisor import ProcessSupervisor, SupervisionConfig

logger = get_logger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"


def setup_logging(log_level: str = "INFO") -> None:
    """Set up logging with the specified level.

    This is a compatibility wrapper around setup_structured_logging
    for tests that expect this function.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    import logging
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MCP Gateway - Aggregate multiple MCP servers into one endpoint"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config.json",
        help="Path to configuration file (default: config.json)",
    )
    parser.add_argument(
        "--host", "-H",
        type=str,
        help="Host to bind to (overrides config)",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        help="Port to listen on (overrides config)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (overrides config)",
    )
    parser.add_argument(
        "--hot-reload",
        action="store_true",
        help="Enable hot reload of configuration file",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Use polling instead of watchdog for hot reload",
    )
    parser.add_argument(
        "--no-supervision",
        action="store_true",
        help="Disable process supervision (auto-restart)",
    )
    parser.add_argument(
        "--console-log",
        action="store_true",
        help="Use console logging instead of JSON",
    )

    return parser.parse_args()


async def create_dependencies(
    config: GatewayConfig,
    config_path: Path,
    args: argparse.Namespace,
    enable_audit_logging: bool = True,
) -> ServerDependencies:
    """Create all server dependencies with explicit injection.

    This is the SINGLE SOURCE OF TRUTH for dependency initialization.
    All services are created here and injected into ServerDependencies.

    Args:
        config: Gateway configuration
        config_path: Path to config file
        args: Command line arguments
        enable_audit_logging: Whether to enable audit logging

    Returns:
        ServerDependencies container with all initialized services
    """
    # Initialize circuit breaker registry
    circuit_breaker_registry = CircuitBreakerRegistry()

    # Create config manager for persistence
    config_manager = ConfigManager(config_path, config)

    # Create backend manager
    backend_manager = BackendManager(
        namespace_separator=config.namespace_separator,
    )

    # Connect to all backends
    try:
        await backend_manager.connect_all(config.servers)
    except Exception as e:
        logger.error("Failed to initialize backends", error=str(e))
        raise

    if not backend_manager.backends:
        raise RuntimeError("No backends connected. Exiting.")

    # Setup process supervision
    supervisor: ProcessSupervisor | None = None
    if not args.no_supervision:
        supervision_config = SupervisionConfig(
            auto_restart=True,
            max_restarts=10,
            max_consecutive_crashes=5,
        )
        supervisor = ProcessSupervisor(backend_manager, supervision_config)
        await supervisor.start_supervision(config.servers)

    # Initialize audit service with file handler if enabled
    audit_handlers = []
    if enable_audit_logging:
        from .audit import FileAuditHandler
        audit_log_path = Path.cwd() / "logs" / "audit.log"
        audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        audit_handlers.append(FileAuditHandler(audit_log_path))
    audit_service = AuditService(handlers=audit_handlers)

    # Initialize security services
    path_security = PathSecurityService()
    config_approval = ConfigApprovalService(
        audit_service=audit_service,
        path_security=path_security,
    )
    access_control = AccessControlManager()
    access_control.start()

    # Initialize auth middleware if API key or bearer token is configured
    auth: AuthMiddleware | None = None
    if config.gateway.api_key or config.gateway.bearer_token:
        auth_config = AuthConfig(
            api_key=config.gateway.api_key,
            bearer_token=config.gateway.bearer_token,
            exclude_paths=config.gateway.auth_exclude_paths,
        )
        auth = AuthMiddleware(config=auth_config)

    # Initialize metrics collector
    metrics = MetricsCollector()

    # Initialize templates
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR)) if TEMPLATE_DIR.exists() else None

    # Create dependencies container
    deps = ServerDependencies(
        config=config,
        backend_manager=backend_manager,
        config_manager=config_manager,
        supervisor=supervisor,
        audit_service=audit_service,
        path_security=path_security,
        access_control=access_control,
        config_approval=config_approval,
        rate_limiter=None,  # Initialized in lifespan
        circuit_breaker_registry=circuit_breaker_registry,
        metrics=metrics,
        auth=auth,
        templates=templates,
    )

    return deps


async def main_async() -> int:
    """Async main function with explicit dependency injection."""
    args = parse_args()

    # Load configuration
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("Configuration file not found", path=str(config_path))
        return 1

    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error("Failed to load configuration", error=str(e))
        return 1

    # Override config with CLI arguments
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.log_level:
        config.log_level = args.log_level

    # Setup logging
    setup_structured_logging(
        log_level=config.log_level,
        json_format=not args.console_log,
        service_name="mcp-gateway"
    )

    logger.info(
        "MCP Gateway Starting",
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )

    # Create dependencies
    try:
        deps = await create_dependencies(config, config_path, args)
    except Exception as e:
        logger.error("Failed to create dependencies", error=str(e))
        return 1

    # Setup hot reload
    hot_reload: HotReloadManager | None = None
    reload_callback: Any = None

    # Note: Hot reload conflicts with config approval - config approval already handles
    # backend restarts when config changes are approved. Using both can cause backends
    # to be restarted twice, leading to errors.
    if args.hot_reload:
        async def reload_callback_impl(new_config: GatewayConfig) -> None:
            """Callback for config reload."""
            logger.info("Applying hot reload...")

            # Check if this change has an active grant (config approval handled it)
            if deps.config_approval:
                active_grants = deps.config_approval.get_active_grants()
                if active_grants:
                    logger.info("Skipping hot reload - config change has active grant(s)")
                    # Just update the config manager without restarting backends
                    if deps.config_manager:
                        deps.config_manager.gateway_config = new_config
                    return

            # Update config manager
            if deps.config_manager:
                deps.config_manager.gateway_config = new_config

            # Stop supervision
            if deps.supervisor:
                await deps.supervisor.stop_supervision()

            # Disconnect old backends
            await deps.backend_manager.disconnect_all()

            # Update backend manager with new separator
            deps.backend_manager._namespace_separator = new_config.namespace_separator

            # Reconnect with new config
            await deps.backend_manager.connect_all(new_config.servers)

            # Restart supervision
            if deps.supervisor and not args.no_supervision:
                await deps.supervisor.start_supervision(new_config.servers)

            # Update metrics
            logger.info(
                "Hot reload complete",
                backends=len(new_config.servers),
                tools=len(deps.backend_manager.get_all_tools()),
            )

        reload_callback = reload_callback_impl

        hot_reload = HotReloadManager(
            config_path=config_path,
            backend_manager=deps.backend_manager,
            config_loader=load_config,
            reconnect_callback=reload_callback,
        )
        await hot_reload.start(use_polling=args.poll)
        logger.info("Hot reload enabled", path=str(config_path))

    # Create server with explicit dependencies (no global state)
    server = McpGatewayServer(dependencies=deps)

    # Create FastAPI app
    app = server.create_app(enable_access_control=True)

    # Setup graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler(sig: int, frame: Any) -> None:
        logger.info("Shutdown signal received", signal=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run server with uvicorn
    try:
        import uvicorn

        config_uvicorn = uvicorn.Config(
            app,
            host=config.host,
            port=config.port,
            log_level=config.log_level.lower(),
        )
        uvicorn_server = uvicorn.Server(config_uvicorn)

        # Run server in a task
        server_task = asyncio.create_task(uvicorn_server.serve())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        done, pending = await asyncio.wait(
            [server_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Check which task completed
        for task in done:
            if task == server_task:
                try:
                    result = task.result()
                    logger.info(f"Server task completed with result: {result}")
                except asyncio.CancelledError:
                    logger.info("Server task was cancelled")
                except Exception as e:
                    logger.error(f"Server task failed with exception: {e}", exc_info=True)
            elif task == shutdown_task:
                logger.info("Shutdown event was set by signal")

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except asyncio.CancelledError:
        logger.info("Main loop received CancelledError")
    except Exception as e:
        logger.error(f"Unexpected error in server main loop: {e}", exc_info=True)
    finally:
        # Cleanup - suppress errors during shutdown
        try:
            if hot_reload:
                logger.info("Stopping hot reload...")
                await hot_reload.stop()
        except Exception:
            pass

        try:
            if deps.supervisor:
                logger.info("Stopping process supervision...")
                await deps.supervisor.stop_supervision()
        except Exception:
            pass

        try:
            if deps.access_control:
                logger.info("Stopping access control...")
                deps.access_control.stop()
        except Exception:
            pass

        try:
            logger.info("Disconnecting from backends...")
            await deps.backend_manager.disconnect_all()
        except asyncio.CancelledError:
            logger.debug("Backend disconnect cancelled")
        except Exception:
            pass

        logger.info("Goodbye!")

    return 0


def _suppress_shutdown_errors():
    """Suppress expected errors during shutdown.

    These errors occur when async generators are closed during exit
    and are not indicative of actual problems.
    """
    import logging
    # Suppress loggers that print errors during shutdown
    for name in ["asyncio", "anyio", "mcp", "trio", "anyio._backends._asyncio"]:
        logging.getLogger(name).setLevel(logging.CRITICAL)

    # Suppress warnings about unclosed async generators
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    warnings.filterwarnings("ignore", message=".*async generator.*")
    warnings.filterwarnings("ignore", message=".*unclosed.*")


def main() -> int:
    """Main entry point."""
    # Check if this is a CLI subcommand (approve/list) or server mode
    if len(sys.argv) > 1 and sys.argv[1] in ("approve", "list"):
        # Delegate to CLI module
        from .cli import main as cli_main
        cli_main()
        return 0

    # Track if we're shutting down to suppress expected errors
    _shutdown_in_progress = False

    def custom_excepthook(exc_type, exc_value, exc_traceback):
        """Suppress expected errors during shutdown."""
        if _shutdown_in_progress:
            # Suppress RuntimeError about cancel scope and GeneratorExit
            if exc_type in (RuntimeError, GeneratorExit):
                return
            # Suppress any error containing specific keywords
            if exc_value:
                msg = str(exc_value).lower()
                suppress_keywords = ["cancel scope", "different task", "async generator", "stdio_client"]
                if any(kw in msg for kw in suppress_keywords):
                    return
            # Check for BaseExceptionGroup (Python 3.11+)
            try:
                if issubclass(exc_type, BaseExceptionGroup):
                    return
            except TypeError:
                pass
        # Call the default excepthook for other errors
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    original_excepthook = sys.excepthook
    sys.excepthook = custom_excepthook

    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        _shutdown_in_progress = True
        _suppress_shutdown_errors()
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.exception("Unexpected error", error=str(e))
        return 1
    finally:
        _suppress_shutdown_errors()
        # Small delay to allow async generators to close
        import time
        time.sleep(0.1)
        sys.excepthook = original_excepthook


if __name__ == "__main__":
    sys.exit(main())
