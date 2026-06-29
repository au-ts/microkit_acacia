# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
from unittest.mock import MagicMock, patch
from acacia.subsystem import Subsystem
from acacia.configstruct import ConfigStruct
from acacia.pd import ProtectionDomain


def create_concrete_subsystem(name="Concrete", **kwargs):
    """Factory producing a minimal concrete Subsystem instance."""
    class ConcreteSubsystem(Subsystem):
        def connect_clients(self):
            pass

    return ConcreteSubsystem(name, **kwargs)


class TestSubsystemInitialization:
    def test_basic_init(self):
        ss = create_concrete_subsystem("test", clients_allowed=True)
        assert ss.name == "test"
        assert ss.clients_allowed is True
        assert ss.built is False
        assert ss.clients == []
        assert ss.pds == []
        assert ss.mrs == []
        assert ss.channels == []

    def test_init_defaults(self):
        ss = create_concrete_subsystem("defaults")
        assert ss.clients_allowed is True

    def test_init_clients_disallowed(self):
        ss = create_concrete_subsystem("noclients", clients_allowed=False)
        assert ss.clients_allowed is False

    def test_forced_prio_accepted_but_not_stored(self):
        # forced_prio remains in the signature for API compatibility but is
        # no longer persisted onto the instance. Passing it must not error,
        # and must not create the attribute.
        ss = create_concrete_subsystem("test", forced_prio=50)
        assert not hasattr(ss, "forced_prio")


class TestSubsystemClientManagement:
    def test_add_client_success(self):
        ss = create_concrete_subsystem("test")
        pd = ProtectionDomain("client", "client.elf", priority=100)
        ss.add_client(pd)
        assert pd in ss.clients

    def test_add_client_not_allowed_raises(self):
        ss = create_concrete_subsystem("test", clients_allowed=False)
        pd = ProtectionDomain("client", "client.elf", priority=100)
        with pytest.raises(RuntimeError, match="does not allow clients"):
            ss.add_client(pd)

    def test_add_duplicate_client_ignored(self):
        ss = create_concrete_subsystem("test")
        pd = ProtectionDomain("client", "client.elf", priority=100)
        ss.add_client(pd)
        ss.add_client(pd)  # Should be a no-op, not raise
        assert len(ss.clients) == 1

    def test_add_multiple_clients_ordered(self):
        ss = create_concrete_subsystem("test")
        pd1 = ProtectionDomain("c1", "c1.elf", priority=10)
        pd2 = ProtectionDomain("c2", "c2.elf", priority=20)
        ss.add_client(pd1)
        ss.add_client(pd2)
        assert ss.clients == [pd1, pd2]



class TestSubsystemGetMethods:
    def test_get_pds_unbuilt_raises(self):
        ss = create_concrete_subsystem("test")
        with pytest.raises(RuntimeError, match="unbuilt subsystem"):
            ss.get_pds()

    def test_get_mrs_unbuilt_raises(self):
        ss = create_concrete_subsystem("test")
        with pytest.raises(RuntimeError, match="unbuilt subsystem"):
            ss.get_mrs()

    def test_get_channels_unbuilt_raises(self):
        ss = create_concrete_subsystem("test")
        with pytest.raises(RuntimeError, match="unbuilt subsystem"):
            ss.get_channels()

    def test_get_pds_post_build(self):
        ss = create_concrete_subsystem("test")
        ss.built = True
        assert ss.get_pds() == []

    def test_get_mrs_post_build(self):
        ss = create_concrete_subsystem("test")
        ss.built = True
        assert ss.get_mrs() == []

    def test_get_channels_post_build(self):
        ss = create_concrete_subsystem("test")
        ss.built = True
        assert ss.get_channels() == []

    def test_get_clients_available_unbuilt(self):
        # Unlike pds/mrs/channels, get_clients() does NOT gate on built.
        ss = create_concrete_subsystem("test")
        pd = ProtectionDomain("client", "client.elf", priority=100)
        ss.add_client(pd)
        assert ss.get_clients() == [pd]

    def test_get_clients_empty(self):
        ss = create_concrete_subsystem("test")
        assert ss.get_clients() == []



class TestGenerateConfigStructs:
    def test_default_returns_empty_list(self):
        ss = create_concrete_subsystem("test")
        assert ss.generate_config_structs() == []

    def test_override_returns_structs(self):
        sentinel = MagicMock(spec=ConfigStruct)

        class WithConfig(Subsystem):
            def connect_clients(self):
                pass

            def generate_config_structs(self):
                return [sentinel]

        ss = WithConfig("cfg")
        assert ss.generate_config_structs() == [sentinel]



class TestSubsystemBuild:
    def test_build_sets_built_flag(self):
        ss = create_concrete_subsystem("test", clients_allowed=False)
        ss.build()
        assert ss.built is True

    def test_build_returns_none(self):
        # Declared `-> int` but the body has no return statement.
        ss = create_concrete_subsystem("test", clients_allowed=False)
        assert ss.build() is None

    def test_build_connects_clients_when_allowed(self):
        ss = create_concrete_subsystem("test", clients_allowed=True)
        with patch.object(ss, "connect_clients") as mock_connect:
            ss.build()
            mock_connect.assert_called_once()

    def test_build_skips_connect_when_not_allowed(self):
        ss = create_concrete_subsystem("test", clients_allowed=False)
        with patch.object(ss, "connect_clients") as mock_connect:
            ss.build()
            mock_connect.assert_not_called()

    def test_build_connects_with_clients_present(self):
        ss = create_concrete_subsystem("test")
        pd = ProtectionDomain("c", "c.elf", priority=10)
        ss.add_client(pd)
        with patch.object(ss, "connect_clients") as mock_connect:
            ss.build()
            mock_connect.assert_called_once()

    def test_build_rebuild_raises(self):
        ss = create_concrete_subsystem("test", clients_allowed=False)
        ss.build()
        with pytest.raises(RuntimeError, match="Cannot build a subsystem more than once"):
            ss.build()

    def test_rebuild_does_not_reconnect(self):
        # The guard must fire before connect_clients runs on a second build.
        ss = create_concrete_subsystem("test", clients_allowed=True)
        ss.build()
        with patch.object(ss, "connect_clients") as mock_connect:
            with pytest.raises(RuntimeError, match="more than once"):
                ss.build()
            mock_connect.assert_not_called()


class TestSubsystemAbstractMethods:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Subsystem("abstract")

    def test_missing_connect_clients_is_abstract(self):
        # connect_clients is the only abstract method; a subclass that omits
        # it cannot be instantiated.
        class Incomplete(Subsystem):
            pass

        with pytest.raises(TypeError):
            Incomplete("incomplete")

    def test_generate_config_structs_not_abstract(self):
        # A subclass providing only connect_clients is concrete, proving
        # generate_config_structs is not part of the abstract contract.
        class Minimal(Subsystem):
            def connect_clients(self):
                pass

        Minimal("minimal")  # Must not raise
