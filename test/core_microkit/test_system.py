# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import xml.etree.ElementTree as et
from unittest.mock import MagicMock, patch, call
from typing import Optional

import pytest

import acacia.system as system_module
from acacia.system import System


@pytest.fixture
def mock_allocator():
    """Patch SDFMemoryAllocator so System.__init__ doesn't need a real Arch."""
    with patch.object(system_module, "SDFMemoryAllocator") as alloc_cls:
        alloc_cls.return_value = MagicMock(name="allocator_instance")
        yield alloc_cls


@pytest.fixture
def arch():
    """A stand-in Arch with a deterministic page size."""
    a = MagicMock(name="arch")
    a.default_page_size.return_value = 0x1000
    return a


@pytest.fixture
def sys_(mock_allocator, arch):
    """A System with all heavy collaborators mocked out."""
    return System(arch, paddr_top=0x8000_0000)


def make_subsystem(pds=(), mrs=(), channels=(), clients=(), built=False):
    """Build a mock Subsystem exposing the assemble contract."""
    ss = MagicMock(name="subsystem")
    ss.get_pds.return_value = list(pds)
    ss.get_mrs.return_value = list(mrs)
    ss.get_channels.return_value = list(channels)
    ss.get_clients.return_value = list(clients)
    ss.built = built
    return ss


class TestSystemInitialization:
    def test_init_stores_arch(self, sys_, arch):
        assert sys_.arch is arch

    def test_init_creates_allocator_with_page_size(self, mock_allocator, arch):
        sys_ = System(arch, paddr_top=0xDEAD_0000)
        mock_allocator.assert_called_once_with(arch, 0xDEAD_0000)
        assert sys_.allocator is mock_allocator.return_value

    def test_init_empty_collections(self, sys_):
        assert sys_.pds == set()
        assert sys_.mrs == set()
        assert sys_.channels == set()
        assert sys_.subsystems == []
        assert sys_.system_assembled is False

    def test_init_collection_types(self, sys_):
        assert isinstance(sys_.pds, set)
        assert isinstance(sys_.mrs, set)
        assert isinstance(sys_.channels, set)
        assert isinstance(sys_.subsystems, list)


class TestEntityRegistration:
    """ProtectionDomain, MemoryRegion and Channel now take the System in
    their constructors and register themselves. These tests exercise the
    registration hooks System exposes for them.
    """

    def test_pd_registration(self, sys_):
        pd = MagicMock(name="pd")
        sys_._add_pd(pd)
        assert pd in sys_.pds

    def test_distinct_pd_registrations(self, sys_):
        pd1, pd2 = MagicMock(), MagicMock()
        sys_._add_pd(pd1)
        sys_._add_pd(pd2)
        assert sys_.pds == {pd1, pd2}

    def test_channel_registration(self, sys_):
        ch = MagicMock(name="channel")
        sys_._add_channel(ch)
        assert ch in sys_.channels

    def test_memory_region_registration(self, sys_):
        mr = MagicMock(name="mr")
        sys_._add_memory_region(mr)
        assert mr in sys_.mrs


class TestAddSubsystem:
    def test__add_subsystem_appends(self, sys_):
        ss = make_subsystem()
        sys_._add_subsystem(ss)
        assert sys_.subsystems == [ss]

    def test__add_subsystem_preserves_order(self, sys_):
        ss1, ss2 = make_subsystem(), make_subsystem()
        sys_._add_subsystem(ss1)
        sys_._add_subsystem(ss2)
        assert sys_.subsystems == [ss1, ss2]

    def test__add_subsystem_allows_duplicates(self, sys_):
        # Unlike pds/mrs/channels, subsystems is a plain list with no dedup.
        ss = make_subsystem()
        sys_._add_subsystem(ss)
        sys_._add_subsystem(ss)
        assert sys_.subsystems == [ss, ss]


class TestResolveSubsystems:
    def test_resolve_empty(self, sys_):
        sys_.resolve_subsystems()
        assert sys_.pds == set()

    def test_resolve_skips_already_built_subsystem(self, sys_):
        """Test that subsystems with built=True are skipped during resolve_subsystems."""
        ss_built = make_subsystem(built=True)
        ss_not_built = make_subsystem(built=False)

        sys_._add_subsystem(ss_built)
        sys_._add_subsystem(ss_not_built)

        sys_.resolve_subsystems()

        # Built subsystem should not have build() called
        ss_built.build.assert_not_called()
        # Not built subsystem should have build() called
        ss_not_built.build.assert_called_once()

    def test_resolve_only_calls_build_on_unbuilt_subsystems(self, sys_):
        """Test that build() is only called on subsystems where built=False."""
        ss1 = make_subsystem(built=True)
        ss2 = make_subsystem(built=False)
        ss3 = make_subsystem(built=True)

        sys_._add_subsystem(ss1)
        sys_._add_subsystem(ss2)
        sys_._add_subsystem(ss3)

        sys_.resolve_subsystems()

        ss1.build.assert_not_called()
        ss2.build.assert_called_once()
        ss3.build.assert_not_called()

    def test_resolve_processes_subsystems_in_order(self, sys_):
        """Test that subsystems are processed in order regardless of built status."""
        order = []
        ss1 = make_subsystem(built=False)
        ss2 = make_subsystem(built=True)
        ss3 = make_subsystem(built=False)

        def make_tracker(name):
            return lambda: order.append(name)

        ss1.build.side_effect = make_tracker("ss1")
        ss2.build.side_effect = make_tracker("ss2")
        ss3.build.side_effect = make_tracker("ss3")

        sys_._add_subsystem(ss1)
        sys_._add_subsystem(ss2)
        sys_._add_subsystem(ss3)

        sys_.resolve_subsystems()

        # Only ss1 and ss3 should be tracked (ss2 is already built)
        assert order == ["ss1", "ss3"]

    def test_resolve_skips_client_addition_for_built_subsystem(self, sys_):
        """Test that clients from built subsystems are not added."""
        client_built = MagicMock(name="client_built")
        client_not_built = MagicMock(name="client_not_built")

        ss_built = make_subsystem(clients=[client_built], built=True)
        ss_not_built = make_subsystem(clients=[client_not_built], built=False)

        sys_._add_subsystem(ss_built)
        sys_._add_subsystem(ss_not_built)

        sys_.resolve_subsystems()

        # Client from built subsystem should NOT be added
        assert client_built not in sys_.pds
        # Client from not built subsystem should be added
        assert client_not_built in sys_.pds


class TestAssemble:
    def test_assemble_calls_resolve_and_auto_allocate(self, sys_):
        """Test that assemble() calls both resolve_subsystems() and auto_allocate()."""
        sys_.resolve_subsystems = MagicMock(wraps=sys_.resolve_subsystems)
        sys_.auto_allocate = MagicMock(wraps=sys_.auto_allocate)

        sys_.assemble()

        sys_.resolve_subsystems.assert_called_once()
        sys_.auto_allocate.assert_called_once()
        assert sys_.system_assembled is True

    def test_assemble_empty(self, sys_):
        sys_.assemble()
        assert sys_.system_assembled is True
        assert sys_.pds == set()

    def test_assemble_calls_build_on_unbuilt_only(self, sys_):
        """Test that assemble() respects the built flag via resolve_subsystems."""
        ss_built = make_subsystem(built=True)
        ss_not_built = make_subsystem(built=False)

        sys_._add_subsystem(ss_built)
        sys_._add_subsystem(ss_not_built)

        sys_.assemble()

        ss_built.build.assert_not_called()
        ss_not_built.build.assert_called_once()
        assert sys_.system_assembled is True

    def test_assemble_collects_entities(self, sys_):
        pd = MagicMock(name="pd")
        mr = MagicMock(name="mr")
        ch = MagicMock(name="ch")
        ss = make_subsystem(pds=[pd], mrs=[mr], channels=[ch])
        sys_._add_subsystem(ss)

        sys_.assemble()

    def test_assemble_adds_clients_as_pds(self, sys_):
        client = MagicMock(name="client")
        ss = make_subsystem(clients=[client])
        sys_._add_subsystem(ss)

        sys_.assemble()

        assert client in sys_.pds

    def test_assemble_skips_already_installed_client(self, sys_):
        # A client shared between two subsystems must only be added once and
        # must NOT trigger the duplicate-PD RuntimeError.
        client = MagicMock(name="shared_client")
        ss1 = make_subsystem(clients=[client])
        ss2 = make_subsystem(clients=[client])
        sys_._add_subsystem(ss1)
        sys_._add_subsystem(ss2)

        sys_.assemble()  # Must not raise

        assert client in sys_.pds

    def test_assemble_client_colliding_with_pd_skipped(self, sys_):
        # If the same object is reported as a PD by one subsystem and a client
        # by another, the client path must skip it rather than re-add.
        shared = MagicMock(name="shared")
        ss1 = make_subsystem(pds=[shared])
        ss2 = make_subsystem(clients=[shared])
        sys_._add_subsystem(ss1)
        sys_._add_subsystem(ss2)

        sys_.assemble()  # Must not raise

        assert shared in sys_.pds

    def test_assemble_sets_constructed_flag(self, sys_):
        ss = make_subsystem()
        sys_._add_subsystem(ss)
        sys_.assemble()
        assert sys_.system_assembled is True

    def test_assemble_processes_subsystems_in_order(self, sys_):
        order = []
        ss1 = make_subsystem()
        ss2 = make_subsystem()
        ss1.build.side_effect = lambda: order.append("ss1")
        ss2.build.side_effect = lambda: order.append("ss2")
        sys_._add_subsystem(ss1)
        sys_._add_subsystem(ss2)

        sys_.assemble()

        assert order == ["ss1", "ss2"]


class TestAutoAllocate:
    def test_auto_allocate_skips_virtual_memory_regions(self, sys_):
        """Test that virtual memory regions (physical=False) are skipped."""
        mr_virtual = MagicMock(name="virtual_mr")
        mr_virtual.physical = False
        mr_virtual.paddr = None

        sys_._add_memory_region(mr_virtual)

        sys_.auto_allocate()

        mr_virtual.allocate_paddr.assert_not_called()

    def test_auto_allocate_skips_preallocated_memory_regions(self, sys_):
        """Test that memory regions with already assigned paddr are skipped."""
        mr_preallocated = MagicMock(name="preallocated_mr")
        mr_preallocated.physical = True
        mr_preallocated.paddr = 0x1000

        sys_._add_memory_region(mr_preallocated)

        sys_.auto_allocate()

        mr_preallocated.allocate_paddr.assert_not_called()

    def test_auto_allocate_allocates_unallocated_physical_regions(self, sys_):
        """Test that physical memory regions without paddr get allocated."""
        mr_unallocated = MagicMock(name="unallocated_mr")
        mr_unallocated.physical = True
        mr_unallocated.paddr = None
        mr_unallocated.allocate_paddr.return_value = 0x2000

        sys_._add_memory_region(mr_unallocated)

        sys_.auto_allocate()

        mr_unallocated.allocate_paddr.assert_called_once_with(sys_.allocator)

    def test_auto_allocate_mixed_memory_regions(self, sys_):
        """Test auto_allocate with a mix of virtual, preallocated, and unallocated regions."""
        mr_virtual = MagicMock(name="virtual_mr")
        mr_virtual.physical = False
        mr_virtual.paddr = None

        mr_preallocated = MagicMock(name="preallocated_mr")
        mr_preallocated.physical = True
        mr_preallocated.paddr = 0x1000

        mr_unallocated1 = MagicMock(name="unallocated_mr1")
        mr_unallocated1.physical = True
        mr_unallocated1.paddr = None

        mr_unallocated2 = MagicMock(name="unallocated_mr2")
        mr_unallocated2.physical = True
        mr_unallocated2.paddr = None

        sys_._add_memory_region(mr_virtual)
        sys_._add_memory_region(mr_preallocated)
        sys_._add_memory_region(mr_unallocated1)
        sys_._add_memory_region(mr_unallocated2)

        sys_.auto_allocate()

        # Only unallocated physical regions should have allocate_paddr called
        mr_virtual.allocate_paddr.assert_not_called()
        mr_preallocated.allocate_paddr.assert_not_called()
        mr_unallocated1.allocate_paddr.assert_called_once_with(sys_.allocator)
        mr_unallocated2.allocate_paddr.assert_called_once_with(sys_.allocator)


class TestRender:
    def test_render_returns_system_element(self, sys_):
        root = sys_.render()
        assert isinstance(root, et.Element)
        assert root.tag == "system"

    def test_render_auto_assembles_when_unconstructed(self, sys_):
        ss = make_subsystem()
        sys_._add_subsystem(ss)
        assert sys_.system_assembled is False

        sys_.render()

        ss.build.assert_called_once()
        assert sys_.system_assembled is True

    def test_render_does_not_reassemble_when_constructed(self, sys_):
        ss = make_subsystem()
        sys_._add_subsystem(ss)
        sys_.assemble()
        ss.build.reset_mock()

        sys_.render()

        ss.build.assert_not_called()

    def test_render_renders_pds(self, sys_):
        pd = MagicMock(name="pd")
        sys_._add_pd(pd)
        sys_.system_assembled = True

        root = sys_.render()

        pd.render.assert_called_once_with(root)

    def test_render_renders_channels(self, sys_):
        ch = MagicMock(name="ch")
        sys_._add_channel(ch)
        sys_.system_assembled = True

        root = sys_.render()

        ch.render.assert_called_once_with(root)

    def test_render_renders_all_entities(self, sys_):
        pd, mr, ch = MagicMock(), MagicMock(), MagicMock()
        sys_._add_pd(pd)
        sys_._add_memory_region(mr)
        sys_._add_channel(ch)
        sys_.system_assembled = True

        root = sys_.render()

        mr.render.assert_called_once_with(root)
        pd.render.assert_called_once_with(root)
        ch.render.assert_called_once_with(root)


class TestWriteXmlFile:
    def test_write_xml_file_invokes_render(self, sys_, tmp_path):
        out = tmp_path / "sys.xml"
        with patch.object(
            sys_, "render", return_value=et.Element("system")
        ) as mock_render:
            sys_.write_xml_file(str(out))
            mock_render.assert_called_once()

    def test_write_xml_file_produces_valid_xml(self, sys_, tmp_path):
        # End-to-end on an empty (but constructed) system: file must parse back.
        sys_.system_assembled = True
        out = tmp_path / "sys.xml"

        sys_.write_xml_file(str(out))

        assert out.exists()
        tree = et.parse(str(out))
        assert tree.getroot().tag == "system"

    def test_write_xml_file_writes_declaration(self, sys_, tmp_path):
        sys_.system_assembled = True
        out = tmp_path / "sys.xml"

        sys_.write_xml_file(str(out))

        content = out.read_text(encoding="utf-8")
        assert content.startswith("<?xml")
