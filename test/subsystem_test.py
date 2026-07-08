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


@pytest.fixture
def sdf():
    """A stand-in System for entity constructors."""
    return System(aarch64, paddr_top=0x10000000)


def create_concrete_subsystem(name="Concrete", sdf=None, **kwargs):
    """Factory producing a minimal concrete Subsystem instance."""
    if sdf is None:
        sdf = System(aarch64, paddr_top=0x10000000)

    class ConcreteSubsystem(Subsystem):
        def connect_clients(self):
            pass

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
        ss = create_concrete_subsystem("noclients", sdf, clients_allowed=False)
        assert ss.clients_allowed is False


class TestSubsystemClientManagement:
    def test_add_client_success(self, sdf):
        ss = create_concrete_subsystem("test", sdf)
        pd = ProtectionDomain(sdf, "client", "client.elf", priority=100)
        ss.add_client(pd)
        assert pd in ss.clients

    def test_add_client_not_allowed_raises(self, sdf):
        ss = create_concrete_subsystem("test", sdf, clients_allowed=False)
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
        ss = create_concrete_subsystem("test", sdf, clients_allowed=False)
        ss.build()
        assert ss.built is True

    def test_build_returns_none(self, sdf):
        # Declared `-> int` but the body has no return statement.
        ss = create_concrete_subsystem("test", sdf, clients_allowed=False)
        assert ss.build() is None

    def test_build_connects_clients_when_allowed(self, sdf):
        ss = create_concrete_subsystem("test", sdf, clients_allowed=True)
        with patch.object(ss, "connect_clients") as mock_connect:
            ss.build()
            mock_connect.assert_called_once()

    def test_build_skips_connect_when_not_allowed(self, sdf):
        ss = create_concrete_subsystem("test", sdf, clients_allowed=False)
        with patch.object(ss, "connect_clients") as mock_connect:
            ss.build()
            mock_connect.assert_not_called()

    def test_build_connects_with_clients_present(self, sdf):
        ss = create_concrete_subsystem("test", sdf)
        pd = ProtectionDomain(sdf, "c", "c.elf", priority=10)
        ss.add_client(pd)
        with patch.object(ss, "connect_clients") as mock_connect:
            ss.build()
            mock_connect.assert_called_once()

    def test_build_rebuild_raises(self, sdf):
        ss = create_concrete_subsystem("test", sdf, clients_allowed=False)
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
