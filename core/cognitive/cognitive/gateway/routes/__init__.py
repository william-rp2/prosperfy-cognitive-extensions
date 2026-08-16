from .health import router as health_router
from .status import router as status_router
from .capabilities import router as capabilities_router

__all__ = ["health_router", "status_router", "capabilities_router"]
