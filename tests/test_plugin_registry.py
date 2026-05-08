"""Tests for Phase 2A: Attack Plugin System (PluginRegistry + @attack decorator)."""

from __future__ import annotations

import pytest

from agentrt.attacks.base import AttackContext, AttackPlugin, attack
from agentrt.attacks.registry import PluginRegistry, RegistryError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure registry is empty before and after every test."""
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()


# ---------------------------------------------------------------------------
# Helper: minimal concrete AttackPlugin for testing
# ---------------------------------------------------------------------------

def _make_plugin_cls(plugin_id: str, name: str = "Test Plugin") -> type[AttackPlugin]:
    """Dynamically create a concrete AttackPlugin subclass WITHOUT registering it."""
    class _Plugin(AttackPlugin):
        async def execute(self, agent, context):
            raise NotImplementedError

    _Plugin.id = plugin_id
    _Plugin.name = name
    _Plugin.category = "A"
    _Plugin.severity = "high"
    _Plugin.__name__ = f"Plugin_{plugin_id}"
    return _Plugin


# ---------------------------------------------------------------------------
# 1. register() / get()
# ---------------------------------------------------------------------------

def test_register_and_get():
    """PluginRegistry.register() stores a plugin; get() retrieves it."""
    cls = _make_plugin_cls("test-01")
    PluginRegistry.register(cls)
    retrieved = PluginRegistry.get("test-01")
    assert retrieved is cls


def test_get_missing_raises_key_error():
    """get() raises KeyError for an unknown plugin id."""
    with pytest.raises(KeyError):
        PluginRegistry.get("does-not-exist")


# ---------------------------------------------------------------------------
# 2. RegistryError on duplicate id
# ---------------------------------------------------------------------------

def test_register_duplicate_raises_registry_error():
    """Registering a plugin with a duplicate id raises RegistryError."""
    cls1 = _make_plugin_cls("dupe-01")
    cls2 = _make_plugin_cls("dupe-01", name="Duplicate")
    PluginRegistry.register(cls1)
    with pytest.raises(RegistryError, match="dupe-01"):
        PluginRegistry.register(cls2)


# ---------------------------------------------------------------------------
# 3. list_all()
# ---------------------------------------------------------------------------

def test_list_all_returns_registered_plugins():
    """list_all() returns all registered plugin classes."""
    assert PluginRegistry.list_all() == []

    cls_a = _make_plugin_cls("list-a")
    cls_b = _make_plugin_cls("list-b")
    PluginRegistry.register(cls_a)
    PluginRegistry.register(cls_b)

    result = PluginRegistry.list_all()
    assert len(result) == 2
    assert cls_a in result
    assert cls_b in result


# ---------------------------------------------------------------------------
# 4. @attack decorator stamps metadata and registers
# ---------------------------------------------------------------------------

def test_attack_decorator_stamps_metadata():
    """@attack stamps id/name/category/severity on the decorated class."""
    @attack(id="dec-01", name="Decorator Test", category="B", severity="medium")
    class _DecoratorPlugin(AttackPlugin):
        async def execute(self, agent, context):
            raise NotImplementedError

    assert _DecoratorPlugin.id == "dec-01"
    assert _DecoratorPlugin.name == "Decorator Test"
    assert _DecoratorPlugin.category == "B"
    assert _DecoratorPlugin.severity == "medium"


def test_attack_decorator_registers_plugin():
    """@attack automatically registers the plugin in PluginRegistry."""
    @attack(id="dec-02", name="Auto Register", category="C", severity="low")
    class _AutoRegPlugin(AttackPlugin):
        async def execute(self, agent, context):
            raise NotImplementedError

    retrieved = PluginRegistry.get("dec-02")
    assert retrieved is _AutoRegPlugin


def test_attack_decorator_duplicate_raises_registry_error():
    """@attack raises RegistryError when the same id is decorated twice."""
    @attack(id="dec-dup", name="First", category="A", severity="high")
    class _First(AttackPlugin):
        async def execute(self, agent, context):
            raise NotImplementedError

    with pytest.raises(RegistryError):
        @attack(id="dec-dup", name="Second", category="A", severity="high")
        class _Second(AttackPlugin):
            async def execute(self, agent, context):
                raise NotImplementedError


# ---------------------------------------------------------------------------
# 5. _import_all_attacks() — walk_packages test
# ---------------------------------------------------------------------------

def test_import_all_attacks_imports_stubs_module():
    """_import_all_attacks() walks agentrt.attacks and imports the stubs module.

    We evict stubs from sys.modules first so that @attack fires fresh and
    registers A01StubPlugin into the (already-cleared) registry.
    """
    import sys

    # Remove stubs from sys.modules to force a fresh import.
    stubs_key = "agentrt.attacks.stubs"
    if stubs_key in sys.modules:
        del sys.modules[stubs_key]

    # Walk-packages should now (re-)import stubs, firing @attack.
    PluginRegistry._import_all_attacks()

    plugin_cls = PluginRegistry.get("A-01-stub")
    assert plugin_cls.__name__ == "A01StubPlugin"


# ---------------------------------------------------------------------------
# 6. discover() — entry-points test (requires editable install)
# ---------------------------------------------------------------------------

def test_discover_loads_entry_point():
    """discover() on a fresh registry registers A01StubPlugin via entry-point.

    Note: because the stubs module is already cached in sys.modules, ep.load()
    returns the already-decorated class without re-firing @attack.  discover()
    must therefore not fail when the module-level @attack already ran before
    discover() was called.  We ensure a clean registry and verify the plugin
    is available after discover().
    """
    import sys

    # Ensure the stubs module triggers @attack fresh by removing it from cache.
    stubs_key = "agentrt.attacks.stubs"
    if stubs_key in sys.modules:
        del sys.modules[stubs_key]

    # Now discover on a clean registry (clear_registry fixture already ran).
    PluginRegistry.discover()
    plugin_cls = PluginRegistry.get("A-01-stub")
    assert plugin_cls.__name__ == "A01StubPlugin"


def test_discover_is_idempotent_on_clean_registry():
    """discover() completes without error on a clean registry."""
    import sys

    stubs_key = "agentrt.attacks.stubs"
    if stubs_key in sys.modules:
        del sys.modules[stubs_key]

    PluginRegistry.discover()
    assert PluginRegistry.get("A-01-stub") is not None


# ---------------------------------------------------------------------------
# 7. clear() isolation
# ---------------------------------------------------------------------------

def test_clear_empties_registry():
    """clear() removes all registered plugins."""
    cls = _make_plugin_cls("clear-01")
    PluginRegistry.register(cls)
    assert len(PluginRegistry.list_all()) == 1

    PluginRegistry.clear()
    assert PluginRegistry.list_all() == []

    with pytest.raises(KeyError):
        PluginRegistry.get("clear-01")


# ---------------------------------------------------------------------------
# 8. A01StubPlugin conformance
# ---------------------------------------------------------------------------

def test_a01_stub_plugin_is_attack_plugin_subclass():
    """A01StubPlugin inherits from AttackPlugin."""
    from agentrt.attacks.stubs import A01StubPlugin
    assert issubclass(A01StubPlugin, AttackPlugin)


def test_a01_stub_plugin_metadata():
    """A01StubPlugin has the expected metadata stamped by @attack."""
    from agentrt.attacks.stubs import A01StubPlugin
    assert A01StubPlugin.id == "A-01-stub"
    assert A01StubPlugin.category == "A"
    assert A01StubPlugin.severity == "high"
    assert len(A01StubPlugin.seed_queries) > 0


@pytest.mark.asyncio
async def test_a01_stub_plugin_execute_raises_not_implemented():
    """A01StubPlugin.execute() raises NotImplementedError (stub behaviour)."""
    from agentrt.attacks.stubs import A01StubPlugin
    plugin = A01StubPlugin()
    with pytest.raises(NotImplementedError):
        await plugin.execute(agent=None, context=None)
