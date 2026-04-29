# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
from unittest.mock import MagicMock, patch
import sdfgenpy.subsystem as subsystem_module
from sdfgenpy.subsystem import (
    Subsystem,
    __DependencyMap,
    DependencyDefinitionError,
    subsystem_register_dependency,
    forced_max_priority,
    get_dependency_map,
)
from sdfgenpy.pd import ProtectionDomain


@pytest.fixture(autouse=True)
def clear_dependency_map():
    """Reset global dependency map before each test."""
    get_dependency_map().clear()


@pytest.fixture
def isolated_depmap():
    """Create an isolated dependency map for testing."""
    return __DependencyMap()


def create_concrete_subsystem(name="Concrete", **kwargs):
    """Factory for creating concrete subsystem classes and instances."""
    class ConcreteSubsystem(Subsystem):
        def connect_clients(self):
            pass

        def construct_infrastructure(self, min_prio: int, max_prio: int, dependencies=None) -> int:
            return min_prio

    return ConcreteSubsystem(name, **kwargs)

# dependency map tests

class TestDependencyMapRegistration:
    def test_register_valid_dependency(self, isolated_depmap):
        class Base(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class Derived(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.register(Derived, Base)
        assert isolated_depmap.dep_map[Derived] == [Base]
        assert isolated_depmap.dep_map[Base] == []  # Auto-initialized

    def test_register_duplicate_raises(self, isolated_depmap):
        class A(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class B(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.register(A, B)
        with pytest.raises(DependencyDefinitionError, match="Cannot register the same subsystem"):
            isolated_depmap.register(A, B)

    def test_register_self_reference_raises(self, isolated_depmap):
        class SelfRef(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        with pytest.raises(DependencyDefinitionError, match="cannot have a dependency on themselves"):
            isolated_depmap.register(SelfRef, SelfRef)

    def test_register_circular_dependency_raises(self, isolated_depmap):
        class A(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class B(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.register(A, B)
        with pytest.raises(DependencyDefinitionError, match="Circular dependency"):
            isolated_depmap.register(B, A)


class TestDependencyMapMaxPriority:
    def test_add_max_prio_system(self, isolated_depmap):
        class MaxPrio(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.add_max_prio_system(MaxPrio)
        assert MaxPrio in isolated_depmap.max_prio_systems

    def test_add_max_prio_with_dependencies_raises(self, isolated_depmap):
        class A(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class B(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.register(B, A)
        with pytest.raises(RuntimeError, match="Cannot be max priority if system depends"):
            isolated_depmap.add_max_prio_system(B)

    def test_add_max_prio_duplicate_raises(self, isolated_depmap):
        class MaxPrio(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.add_max_prio_system(MaxPrio)
        with pytest.raises(DependencyDefinitionError, match="Cannot define max prio multiple times"):
            isolated_depmap.add_max_prio_system(MaxPrio)


class TestDependencyMapTopologicalSort:
    def test_empty_graph(self, isolated_depmap):
        result = isolated_depmap.topological_sort()
        assert result == []

    def test_linear_chain(self, isolated_depmap):
        class A(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class B(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class C(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.register(B, A)
        isolated_depmap.register(C, B)

        result = isolated_depmap.topological_sort()
        assert result.index(A) > result.index(B)
        assert result.index(B) > result.index(C)

    def test_diamond_dependency(self, isolated_depmap):
        class Bottom(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class Left(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class Right(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class Top(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.register(Left, Bottom)
        isolated_depmap.register(Right, Bottom)
        isolated_depmap.register(Top, Left)
        isolated_depmap.register(Top, Right)

        result = isolated_depmap.topological_sort()
        assert result.index(Bottom) > result.index(Left)
        assert result.index(Bottom) > result.index(Right)
        assert result.index(Left) > result.index(Top)
        assert result.index(Right) > result.index(Top)

    def test_cycle_detection(self, isolated_depmap):
        class A(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class B(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        # Note: direct cycle (A->B, B->A) is caught at registration time
        # This tests indirect cycles via DFS
        class C(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.register(B, A)
        isolated_depmap.register(C, B)
        isolated_depmap.register(A, C)

        with pytest.raises(RuntimeError, match="Circular dependency found"):
            isolated_depmap.topological_sort()

    def test_max_priority_reordering(self, isolated_depmap):
        class A(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class MaxPrio(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        class B(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        isolated_depmap.register(B, A)
        isolated_depmap.add_max_prio_system(MaxPrio)

        result = isolated_depmap.topological_sort()
        # Max prio should be at the end, despite having no deps
        assert result[-1] == MaxPrio
        assert A in result[:-1]
        assert B in result[:-1]


# subsystem API tests

class TestSubsystemRegisterDependency:
    def test_valid_registration(self, clear_dependency_map):
        class Base(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        @subsystem_register_dependency(Base)
        class Derived(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        dep_map = get_dependency_map()
        assert Derived in dep_map.dep_map
        assert Base in dep_map.dep_map[Derived]

    def test_non_subsystem_raises(self, clear_dependency_map):
        with pytest.raises(TypeError, match="Only subclasses of.*Subsystem"):
            @subsystem_register_dependency(int)
            class NotASubsystem:
                pass

    def test_decorator_preserves_class(self, clear_dependency_map):
        class Base(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        @subsystem_register_dependency(Base)
        class Derived(Subsystem):
            custom_attr = "test"
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        assert Derived.custom_attr == "test"
        assert issubclass(Derived, Subsystem)


class TestForcedMaxPriority:
    def test_max_prio_decorator(self, clear_dependency_map):
        @forced_max_priority
        class MaxPrio(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        dep_map = get_dependency_map()
        assert MaxPrio in dep_map.max_prio_systems
        assert hasattr(MaxPrio, "force_max_prio")

    def test_max_prio_with_deps_raises(self, clear_dependency_map):
        class Base(Subsystem):
            def connect_clients(self): pass
            def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

        with pytest.raises(RuntimeError, match="Cannot be max priority"):
            @forced_max_priority
            @subsystem_register_dependency(Base)
            class MaxPrio(Subsystem):
                def connect_clients(self): pass
                def construct_infrastructure(self, min_prio, max_prio, dependencies=None): return min_prio

    def test_non_subsystem_raises(self, clear_dependency_map):
        with pytest.raises(TypeError, match="This decorator only operates on subsystem"):
            @forced_max_priority
            class NotASubsystem:
                pass


# -----------------------------------------------------------------------------
# Tests for Subsystem Base Class
# -----------------------------------------------------------------------------

class TestSubsystemInitialization:
    def test_basic_init(self):
        ss = create_concrete_subsystem("test", clients_allowed=True, forced_prio=50)
        assert ss.name == "test"
        assert ss.clients_allowed is True
        assert ss.forced_prio == 50
        assert ss.built is False
        assert ss.clients == []
        assert ss.pds == []
        assert ss.mrs == []
        assert ss.channels == []

    def test_init_defaults(self):
        ss = create_concrete_subsystem("defaults")
        assert ss.clients_allowed is True
        assert ss.forced_prio is None


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
        ss.add_client(pd)  # Should not raise
        assert len(ss.clients) == 1


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

    def test_get_clients(self):
        ss = create_concrete_subsystem("test")
        pd = ProtectionDomain("client", "client.elf", priority=100)
        ss.add_client(pd)
        assert ss.get_clients() == [pd]


class TestSubsystemBuild:
    def test_build_no_clients(self):
        ss = create_concrete_subsystem("test", clients_allowed=False)
        with patch.object(ss, 'construct_infrastructure', return_value=0) as mock_infra:
            result = ss.build(min_priority=0, dependencies={})
            mock_infra.assert_called_once_with(0, 255, dependencies={})
            assert result == 0

    def test_build_with_clients_priority_calculation(self):
        ss = create_concrete_subsystem("test")
        pd1 = ProtectionDomain("c1", "c1.elf", priority=100)
        pd2 = ProtectionDomain("c2", "c2.elf", priority=150)
        ss.add_client(pd1)
        ss.add_client(pd2)

        # min_c_prio = max(100, 150) + 1 = 151
        # With min_priority=200, construct_infrastructure should be called with min_prio=200
        with patch.object(ss, 'construct_infrastructure', return_value=200) as mock_infra:
            result = ss.build(min_priority=200, dependencies={})
            mock_infra.assert_called_once_with(200, 255, dependencies={})
            assert result == 200

    # no longer needed
    # def test_build_impossible_priority_range(self):
    #     ss = create_concrete_subsystem("test")
    #     pd = ProtectionDomain("c", "c.elf", priority=150)
    #     ss.add_client(pd)
    #
    #     # min_c_prio = 151, min_priority = 100 -> 151 > 100, should raise
    #     with pytest.raises(RuntimeError, match="Subsystem cannot be implemented"):
    #         ss.build(min_priority=100, dependencies={})

    def test_build_priority_range_boundary(self):
        """Test boundary condition where min_c_prio equals min_priority."""
        ss = create_concrete_subsystem("test")
        pd = ProtectionDomain("c", "c.elf", priority=149)
        ss.add_client(pd)

        # min_c_prio = 150, min_priority = 150 -> 150 > 150 is False, should succeed
        with patch.object(ss, 'construct_infrastructure', return_value=150) as mock_infra:
            result = ss.build(min_priority=150, dependencies={})
            mock_infra.assert_called_once_with(150, 255, dependencies={})

    def test_build_connects_clients(self):
        ss = create_concrete_subsystem("test")
        pd = ProtectionDomain("c", "c.elf", priority=10)
        ss.add_client(pd)

        with patch.object(ss, 'connect_clients') as mock_connect:
            ss.build(min_priority=20, dependencies={})
            mock_connect.assert_called_once()

    def test_build_skips_connect_when_not_allowed(self):
        ss = create_concrete_subsystem("test", clients_allowed=False)

        with patch.object(ss, 'construct_infrastructure', return_value=0):
            with patch.object(ss, 'connect_clients') as mock_connect:
                ss.build(min_priority=0, dependencies={})
                mock_connect.assert_not_called()

    def test_build_rebuild_raises(self):
        ss = create_concrete_subsystem("test", clients_allowed=False)
        with patch.object(ss, 'construct_infrastructure', return_value=0):
            ss.build(min_priority=0, dependencies={})
            with pytest.raises(RuntimeError, match="Cannot build a subsystem more than once"):
                ss.build(min_priority=0, dependencies={})


class TestSubsystemAbstractMethods:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Subsystem("abstract")

