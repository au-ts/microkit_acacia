# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import xml.etree.ElementTree as et
from unittest.mock import MagicMock, patch, call
from typing import Optional

import pytest

import acacia.system as system_module
from acacia.system import System
from acacia.memory import MemoryRegion


@pytest.fixture
def arch():
    """A stand-in Arch with a deterministic page size."""
    a = MagicMock(name="arch")
    a.default_page_size.return_value = 0x1000
    return a


@pytest.fixture
def sys_(arch):
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

        mr_virtual._set_paddr.assert_not_called()

    def test_auto_allocate_skips_preallocated_memory_regions(self, sys_):
        """Test that memory regions with already assigned paddr are skipped."""
        mr_preallocated = MagicMock(name="preallocated_mr")
        mr_preallocated.physical = True
        mr_preallocated.paddr = 0x1000

        sys_._add_memory_region(mr_preallocated)

        sys_.auto_allocate()

        mr_preallocated._set_paddr.assert_not_called()

    def test_auto_allocate_mixed_memory_regions(self, sys_):
        """Test auto_allocate with a mix of virtual, preallocated, and unallocated regions."""
        mr_virtual = MagicMock(name="virtual_mr")
        mr_virtual.physical = False
        mr_virtual.paddr = None

        mr_preallocated = MagicMock(name="preallocated_mr")
        mr_preallocated.physical = True
        mr_preallocated.paddr = 0x1000
        mr_preallocated.name = "a"
        mr_preallocated.size = 0x1000

        mr_unallocated1 = MagicMock(name="unallocated_mr1")
        mr_unallocated1.physical = True
        mr_unallocated1.paddr = None
        mr_unallocated1.name = "b"
        mr_unallocated1.size = 0x1000

        mr_unallocated2 = MagicMock(name="unallocated_mr2")
        mr_unallocated2.physical = True
        mr_unallocated2.paddr = None
        mr_unallocated2.name = "c"
        mr_unallocated2.size = 0x1000

        sys_._add_memory_region(mr_virtual)
        sys_._add_memory_region(mr_preallocated)
        sys_._add_memory_region(mr_unallocated1)
        sys_._add_memory_region(mr_unallocated2)

        sys_.auto_allocate()

        # Only unallocated physical regions should have _set_paddr called
        mr_virtual._set_paddr.assert_not_called()
        mr_preallocated._set_paddr.assert_not_called()
        mr_unallocated1._set_paddr.assert_called_once()
        mr_unallocated2._set_paddr.assert_called_once()

    def test_auto_allocate_allocates_unallocated_physical_regions(self, sys_):
        """Test that physical memory regions without paddr get allocated."""
        mr = MemoryRegion(sys_, "unallocated_mr", 0x1000, physical=True)

        sys_.auto_allocate()

        # Should have been allocated
        assert mr.paddr is not None
        # Should be page-aligned
        assert mr.paddr % 0x1000 == 0

    def test_auto_allocate_mixed_memory_regions(self, sys_):
        """Test auto_allocate with a mix of virtual, preallocated, and unallocated regions."""
        mr_virtual = MemoryRegion(sys_, "virtual_mr", 0x1000, physical=False)
        mr_preallocated = MemoryRegion(sys_, "preallocated_mr", 0x1000, paddr=0x1000)
        mr_unallocated1 = MemoryRegion(sys_, "unallocated_mr1", 0x1000, physical=True)
        mr_unallocated2 = MemoryRegion(sys_, "unallocated_mr2", 0x1000, physical=True)

        sys_.auto_allocate()

        # Only unallocated physical regions should have been allocated
        assert mr_virtual.paddr is None  # virtual, untouched
        assert mr_preallocated.paddr == 0x1000  # preallocated, unchanged
        assert mr_unallocated1.paddr is not None  # allocated
        assert mr_unallocated2.paddr is not None  # allocated

    def test_auto_allocate_single_unallocated_from_top(self, sys_):
        """Test that allocation starts from paddr_top when no other regions exist."""
        mr = MemoryRegion(sys_, "region_a", 0x1000, physical=True)

        sys_.auto_allocate()

        # Should allocate at paddr_top, page-aligned
        expected_paddr = sys_.paddr_top - 0x1000
        expected_paddr = expected_paddr & ~0xFFF
        assert mr.paddr == expected_paddr

    def test_size_align_enforced(self, sys_):
        """Test that MRs with non-aligned addresses are rejected"""
        mr = MemoryRegion(
            sys_, "unaligned_mr", 0x1234, physical=True
        )  # Non-page-aligned size

        with pytest.raises(RuntimeError, match="page-unaligned"):
            sys_.auto_allocate()

    def test_auto_allocate_between_two_preallocated_regions(self, sys_):
        """Test allocation into a gap between two preallocated regions."""
        sys_.paddr_top = 0x7000_3000
        # Preallocate regions with a gap between them
        mr_low = MemoryRegion(sys_, "low_region", 0x1000, paddr=0x7000_0000)
        mr_high = MemoryRegion(sys_, "high_region", 0x1000, paddr=0x7000_2000)

        # Unallocated region that should fit in the gap
        mr_unalloc = MemoryRegion(sys_, "gap_region", 0x1000, physical=True)

        sys_.auto_allocate()

        # Should allocate in the gap at 0x7000_1000 (page-aligned)
        assert mr_unalloc.paddr == 0x7000_1000

    def test_auto_allocate_multiple_in_sequence(self, sys_):
        """Test allocating multiple regions after each other."""
        mr1 = MemoryRegion(sys_, "region_a", 0x1000, physical=True)
        mr2 = MemoryRegion(sys_, "region_b", 0x1000, physical=True)
        mr3 = MemoryRegion(sys_, "region_c", 0x1000, physical=True)

        sys_.auto_allocate()

        # All should have been allocated
        assert mr1.paddr is not None
        assert mr2.paddr is not None
        assert mr3.paddr is not None

        # Should be page-aligned
        assert mr1.paddr % 0x1000 == 0
        assert mr2.paddr % 0x1000 == 0
        assert mr3.paddr % 0x1000 == 0

    def test_auto_allocate_respects_preallocated_addresses(self, sys_):
        """Test that preallocated regions' addresses are never modified."""
        mr_pre = MemoryRegion(sys_, "preallocated", 0x1000, paddr=0x7000_1000)
        mr_unalloc = MemoryRegion(sys_, "unallocated", 0x1000, physical=True)

        sys_.auto_allocate()

        # Preallocated should not be touched
        assert mr_pre.paddr == 0x7000_1000

        # Unallocated should get an address
        assert mr_unalloc.paddr is not None

    def test_auto_allocate_with_gap_below_preallocated(self, sys_):
        """Test allocation in gap below a preallocated region."""
        mr_pre = MemoryRegion(sys_, "preallocated", 0x1000, paddr=0x7000_0000)
        mr_unalloc = MemoryRegion(sys_, "unallocated", 0x1000, physical=True)

        sys_.auto_allocate()

        # Unallocated should be placed above preallocated with paddr_top=8000_0000
        assert mr_unalloc.paddr is not None
        assert mr_unalloc.paddr % 0x1000 == 0
        assert mr_unalloc.paddr + 0x1000 > 0x7000_0000

    def test_auto_allocate_finds_best_gap(self, sys_):
        """Test that allocator finds the gap closest to paddr_top."""
        sys_.paddr_top = 0x7000_4000
        mr_highest = MemoryRegion(sys_, "highest", 0x1000, paddr=0x7000_3000)
        mr_low = MemoryRegion(sys_, "low", 0x1000, paddr=0x7000_0000)
        mr_unalloc = MemoryRegion(sys_, "unallocated", 0x1000, physical=True)

        sys_.auto_allocate()

        # Should allocate in the gap at 0x7000_2000-0x7000_3000 (the higher gap)
        assert mr_unalloc.paddr == 0x7000_2000

    def test_auto_allocate_region_too_large_for_gap(self, sys_):
        """Test that allocation skips gaps that are too small."""
        mr_pre1 = MemoryRegion(sys_, "pre1", 0x1000, paddr=0x7FFF_F000)
        mr_pre2 = MemoryRegion(sys_, "pre2", 0x1000, paddr=0x7FFF_C000)

        # Region that's too large for the gap between pre1 and pre2
        mr_unalloc = MemoryRegion(sys_, "unallocated", 0x3000, physical=True)

        sys_.auto_allocate()

        # Should allocate below the lowest preallocated region
        assert mr_unalloc.paddr is not None
        assert mr_unalloc.paddr + 0x3000 <= mr_pre2.paddr

    def test_auto_allocate_consistency_by_name(self, sys_):
        """Test that allocation order is deterministic based on name."""
        mr_zebra = MemoryRegion(sys_, "zebra", 0x1000, physical=True)
        mr_apple = MemoryRegion(sys_, "apple", 0x1000, physical=True)

        sys_.auto_allocate()

        # Both should be allocated
        assert mr_zebra.paddr is not None
        assert mr_apple.paddr is not None

        # Due to sorting by name (reverse), "zebra" should come second in allocation
        assert mr_zebra.paddr < mr_apple.paddr

    def test_auto_allocate_empty_system(self, sys_):
        """Test that auto_allocate handles empty system gracefully."""
        sys_.auto_allocate()
        # Should not raise any errors

    def test_auto_allocate_all_preallocated(self, sys_):
        """Test that auto_allocate handles system with only preallocated regions."""
        mr1 = MemoryRegion(sys_, "region1", 0x1000, paddr=0x7000_0000)
        mr2 = MemoryRegion(sys_, "region2", 0x1000, paddr=0x7000_1000)

        sys_.auto_allocate()

        # None should have been modified
        assert mr1.paddr == 0x7000_0000
        assert mr2.paddr == 0x7000_1000

    def test_auto_allocate_with_virtual_regions(self, sys_):
        """Test that virtual regions are completely ignored."""
        mr_virtual = MemoryRegion(sys_, "virtual", 0x1000, physical=False)
        mr_physical = MemoryRegion(sys_, "physical", 0x1000, physical=True)

        sys_.auto_allocate()

        # Virtual region should not be touched
        assert mr_virtual.paddr is None

        # Physical region should be allocated
        assert mr_physical.paddr is not None

    def test_auto_allocate_updates_used_range_during_allocation(self, sys_):
        """Test that later allocations account for earlier auto-allocated regions."""
        # First allocation will place a region, so second allocation
        # should account for it being in used_range
        mr1 = MemoryRegion(sys_, "region_a", 0x1000, physical=True)
        mr2 = MemoryRegion(sys_, "region_b", 0x1000, physical=True)

        sys_.auto_allocate()

        # Both allocated
        assert mr1.paddr is not None
        assert mr2.paddr is not None

        # Should be page-aligned and non-overlapping
        assert mr1.paddr % 0x1000 == 0
        assert mr2.paddr % 0x1000 == 0
        # Each region is 0x1000, so they shouldn't overlap
        assert abs(mr1.paddr - mr2.paddr) >= 0x1000


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
