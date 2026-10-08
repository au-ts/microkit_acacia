# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
from unittest.mock import MagicMock, patch
from acacia.subsystem import Subsystem
from acacia.configstruct import ConfigStruct
from acacia.pd import ProtectionDomain
from acacia.memory import MemoryRegion
from acacia.system import System
from acacia.arch import aarch64
from acacia.subsystem import SubsystemBuildError, build_hook


@pytest.fixture
def sdf():
    """A stand-in System for entity constructors."""
    return System(aarch64, paddr_top=0x10000000)


def create_concrete_subsystem_noclients(name="Concrete", sdf=None, **kwargs):
    """Factory producing a minimal concrete Subsystem instance."""
    if sdf is None:
        sdf = System(aarch64, paddr_top=0x10000000)

    class ConcreteSubsystem(Subsystem):
        pass

    return ConcreteSubsystem(sdf, name, **kwargs)


def create_concrete_subsystem(name="Concrete", sdf=None, **kwargs):
    """Factory producing a minimal concrete Subsystem instance."""
    if sdf is None:
        sdf = System(aarch64, paddr_top=0x10000000)

    class ConcreteSubsystem(Subsystem):
        @build_hook
        def connect_clients(self):
            self.connected = True

    return ConcreteSubsystem(sdf, name, **kwargs)


class TestSubsystemInitialization:
    def test_basic_init(self, sdf):
        ss = create_concrete_subsystem("test", sdf, clients_allowed=True)
        assert ss.name == "test"
        assert ss.clients_allowed is True
        assert ss.built is False
        assert ss.clients == []

    def test_init_defaults(self, sdf):
        ss = create_concrete_subsystem("defaults", sdf)
        assert ss.clients_allowed is True

    def test_init_clients_disallowed(self, sdf):
        ss = create_concrete_subsystem_noclients(
            "noclients", sdf, clients_allowed=False
        )
        assert ss.clients_allowed is False


class TestSubsystemClientManagement:
    def test_add_client_success(self, sdf):
        ss = create_concrete_subsystem("test", sdf)
        pd = ProtectionDomain(sdf, "client", "client.elf", priority=100)
        ss.add_client(pd)
        assert pd in ss.clients

    def test_add_client_not_allowed_raises(self, sdf):
        ss = create_concrete_subsystem_noclients("test", sdf, clients_allowed=False)
        pd = ProtectionDomain(sdf, "client", "client.elf", priority=100)
        with pytest.raises(RuntimeError, match="does not allow clients"):
            ss.add_client(pd)

    def test_add_duplicate_client_ignored(self, sdf):
        ss = create_concrete_subsystem("test", sdf)
        pd = ProtectionDomain(sdf, "client", "client.elf", priority=100)
        ss.add_client(pd)
        ss.add_client(pd)  # Should be a no-op, not raise
        assert len(ss.clients) == 1

    def test_add_multiple_clients_ordered(self, sdf):
        ss = create_concrete_subsystem("test", sdf)
        pd1 = ProtectionDomain(sdf, "c1", "c1.elf", priority=10)
        pd2 = ProtectionDomain(sdf, "c2", "c2.elf", priority=20)
        ss.add_client(pd1)
        ss.add_client(pd2)
        assert ss.clients == [pd1, pd2]


class TestSubsystemGetMethods:
    def test_get_clients_available_unbuilt(self, sdf):
        # Unlike pds/mrs/channels, get_clients() does NOT gate on built.
        ss = create_concrete_subsystem("test", sdf)
        pd = ProtectionDomain(sdf, "client", "client.elf", priority=100)
        ss.add_client(pd)
        assert ss.get_clients() == [pd]

    def test_get_clients_empty(self, sdf):
        ss = create_concrete_subsystem("test", sdf)
        assert ss.get_clients() == []


class TestGenerateConfigStructs:
    def test_default_returns_empty_list(self, sdf):
        ss = create_concrete_subsystem("test", sdf)
        assert ss.generate_config_structs() == []

    def test_override_returns_structs(self, sdf):
        sentinel = MagicMock(spec=ConfigStruct)

        class WithConfig(Subsystem):
            def connect_clients(self):
                pass

            def generate_config_structs(self):
                return [sentinel]

        ss = WithConfig(sdf, "cfg")
        assert ss.generate_config_structs() == [sentinel]


class TestSubsystemBuild:
    def test_build_sets_built_flag(self, sdf):
        ss = create_concrete_subsystem_noclients("test", sdf, clients_allowed=False)
        ss.build()
        assert ss.built is True

    def test_build_returns_none(self, sdf):
        # Declared `-> int` but the body has no return statement.
        ss = create_concrete_subsystem_noclients("test", sdf, clients_allowed=False)
        assert ss.build() is None

    def test_build_connects_clients_when_allowed(self, sdf):
        ss = create_concrete_subsystem("test", sdf, clients_allowed=True)
        ss.build()
        assert ss.connected

    def test_build_connects_with_clients_present(self, sdf):
        ss = create_concrete_subsystem("test", sdf)
        pd = ProtectionDomain(sdf, "c", "c.elf", priority=10)
        ss.add_client(pd)
        ss.build()
        assert ss.connected

    def test_build_rebuild_raises(self, sdf):
        ss = create_concrete_subsystem_noclients("test", sdf, clients_allowed=False)
        ss.build()
        with pytest.raises(
            RuntimeError, match="Cannot build a subsystem more than once"
        ):
            ss.build()

    def test_rebuild_does_not_reconnect(self, sdf):
        # The guard must fire before connect_clients runs on a second build.
        ss = create_concrete_subsystem("test", sdf, clients_allowed=True)
        ss.build()
        with patch.object(ss, "connect_clients") as mock_connect:
            with pytest.raises(RuntimeError, match="more than once"):
                ss.build()
            mock_connect.assert_not_called()


class TestSubsystemAbstractMethods:
    def test_cannot_instantiate_abstract(self, sdf):
        with pytest.raises(TypeError):
            Subsystem(sdf, "abstract")

    def test_generate_config_structs_not_abstract(self, sdf):
        # A subclass providing only connect_clients is concrete, proving
        # generate_config_structs is not part of the abstract contract.
        class Minimal(Subsystem):
            def connect_clients(self):
                pass

        Minimal(sdf, "minimal")  # Must not raise


class TestSubsystemBuildHooks:
    def test_decorated_hooks_run_in_declaration_order(self, sdf):
        calls = []

        class OrderedHooks(Subsystem):
            @build_hook
            def first_hook(self):
                calls.append("first")

            def ordinary_method(self):
                calls.append("ordinary")

            @build_hook
            def second_hook(self):
                calls.append("second")

        ss = OrderedHooks(sdf, "ordered")

        assert ss.build_hooks == [ss.first_hook, ss.second_hook]
        assert calls == []

        ss.build()

        assert calls == ["first", "second"]

    def test_build_hooks_are_bound_to_each_instance(self, sdf):
        class PerInstanceHooks(Subsystem):
            @build_hook
            def record_name(self):
                self.calls.append(self.name)

        first = PerInstanceHooks(sdf, "first")
        second = PerInstanceHooks(sdf, "second")
        first.calls = []
        second.calls = []

        assert first.build_hooks == [first.record_name]
        assert second.build_hooks == [second.record_name]
        assert first.build_hooks != second.build_hooks

        first.build()

        assert first.calls == ["first"]
        assert second.calls == []

        second.build()

        assert second.calls == ["second"]

    def test_inherited_hooks_run_before_subclass_hooks(self, sdf):
        calls = []

        class ParentSubsystem(Subsystem):
            @build_hook
            def parent_hook(self):
                calls.append("parent")

        class ChildSubsystem(ParentSubsystem):
            @build_hook
            def child_hook(self):
                calls.append("child")

        ss = ChildSubsystem(sdf, "child")

        assert ss.build_hooks == [ss.parent_hook, ss.child_hook]

        ss.build()

        assert calls == ["parent", "child"]

    def test_undecorated_override_removes_inherited_hook(self, sdf):
        calls = []

        class ParentSubsystem(Subsystem):
            @build_hook
            def inherited_hook(self):
                calls.append("parent")

        class ChildSubsystem(ParentSubsystem):
            def inherited_hook(self):
                calls.append("child")

        ss = ChildSubsystem(sdf, "unmarked-override")

        assert ss.build_hooks == []

        ss.build()

        assert calls == []

    def test_decorated_override_replaces_inherited_hook(self, sdf):
        calls = []

        class ParentSubsystem(Subsystem):
            @build_hook
            def inherited_hook(self):
                calls.append("parent")

        class ChildSubsystem(ParentSubsystem):
            @build_hook
            def inherited_hook(self):
                calls.append("child")

        ss = ChildSubsystem(sdf, "decorated-override")

        assert ss.build_hooks == [ss.inherited_hook]

        ss.build()

        assert calls == ["child"]

    def test_mro_shadowing_does_not_register_unmarked_method(self, sdf):
        calls = []

        class UnhookedParent(Subsystem):
            def shared_method(self):
                calls.append("unhooked")

        class HookedParent(Subsystem):
            @build_hook
            def shared_method(self):
                calls.append("hooked")

        class UnhookedFirst(UnhookedParent, HookedParent):
            pass

        class HookedFirst(HookedParent, UnhookedParent):
            pass

        unhooked_first = UnhookedFirst(sdf, "unhooked-first")
        hooked_first = HookedFirst(sdf, "hooked-first")

        assert unhooked_first.build_hooks == []
        assert hooked_first.build_hooks == [hooked_first.shared_method]

        unhooked_first.build()
        hooked_first.build()

        assert calls == ["hooked"]
