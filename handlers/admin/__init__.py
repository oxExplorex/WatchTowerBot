from .admin_menu_handler import router

from .admins_handler import router
from .apps_manager import router
from .panel import router
from .proxy_manager import router
from .reboot import router
from .settings import router


__all__ = ["router"]
