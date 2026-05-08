from __future__ import annotations

import importlib
import importlib.metadata
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from agentrt.attacks.base import AttackPlugin


class RegistryError(Exception):
    """Raised when a plugin registration error occurs."""


class PluginRegistry:
    _plugins: ClassVar[dict[str, type[AttackPlugin]]] = {}

    @classmethod
    def register(cls, plugin_cls: type[AttackPlugin]) -> None:
        """Register a plugin class. Raises RegistryError on duplicate id."""
        plugin_id = plugin_cls.id
        if plugin_id in cls._plugins:
            raise RegistryError(
                f"Plugin with id '{plugin_id}' is already registered "
                f"(existing: {cls._plugins[plugin_id].__name__}, "
                f"new: {plugin_cls.__name__})"
            )
        cls._plugins[plugin_id] = plugin_cls

    @classmethod
    def get(cls, plugin_id: str) -> type[AttackPlugin]:
        """Retrieve a plugin class by id. Raises KeyError if not found."""
        return cls._plugins[plugin_id]

    @classmethod
    def list_all(cls) -> list[type[AttackPlugin]]:
        """Return a list of all registered plugin classes."""
        return list(cls._plugins.values())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered plugins. Use for test isolation."""
        cls._plugins.clear()

    @classmethod
    def discover(cls) -> None:
        """Discover and load all attack plugins (both built-ins and entry-points)."""
        cls._import_all_attacks()
        for ep in importlib.metadata.entry_points(group="agentrt.attacks"):
            ep.load()

    @classmethod
    def _import_all_attacks(cls) -> None:
        """Walk the agentrt.attacks package and import all submodules."""
        import pkgutil

        import agentrt.attacks as pkg

        for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
            importlib.import_module(modname)
