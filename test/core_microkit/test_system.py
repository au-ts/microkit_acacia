# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import xml.etree.ElementTree as et
from unittest.mock import MagicMock, patch, call

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


def make_subsystem(pds=(), mrs=(), channels=(), clients=()):
    """Build a mock Subsystem exposing the resolve_subsystems contract."""
    ss = MagicMock(name="subsystem")
    ss.get_pds.return_value = list(pds)
    ss.get_mrs.return_value = list(mrs)
    ss.get_channels.return_value = list(channels)
    ss.get_clients.return_value = list(clients)
    return ss


class TestSystemInitialization:
    def test_init_stores_arch(self, sys_, arch):
        assert sys_.arch is arch

    def test_init_creates_allocator_with_page_size(self, mock_allocator, arch):
        sys_ = System(arch, paddr_top=0xDEAD_0000)
        mock_allocator.assert_called_once_with(arch, 0xDEAD_0000, 0x1000)
        assert sys_.allocator is mock_allocator.return_value

    def test_init_empty_collections(self, sys_):
        assert sys_.pds == set()
        assert sys_.mrs == set()
        assert sys_.channels == set()
        assert sys_.subsystems == []
        assert sys_.subsystems_constructed is False

    def test_init_collection_types(self, sys_):
        assert isinstance(sys_.pds, set)
        assert isinstance(sys_.mrs, set)
        assert isinstance(sys_.channels, set)
        assert isinstance(sys_.subsystems, list)


class TestAddPd:
    def test_add_pd_success(self, sys_):
        pd = MagicMock(name="pd")
        sys_.add_pd(pd)
        assert pd in sys_.pds

    def test_add_duplicate_pd_raises(self, sys_):
        pd = MagicMock(name="pd")
        sys_.add_pd(pd)
        with pytest.raises(RuntimeError, match="Cannot add one PD to the same system multiple times"):
            sys_.add_pd(pd)

    def test_add_distinct_pds(self, sys_):
        pd1, pd2 = MagicMock(), MagicMock()
        sys_.add_pd(pd1)
        sys_.add_pd(pd2)
        assert sys_.pds == {pd1, pd2}


class TestAddChannel:
    def test_add_channel_success(self, sys_):
        ch = MagicMock(name="channel")
        sys_.add_channel(ch)
        assert ch in sys_.channels

    def test_add_duplicate_channel_raises(self, sys_):
        ch = MagicMock(name="channel")
        sys_.add_channel(ch)
        with pytest.raises(RuntimeError, match="Cannot add one channel to the same system multiple times"):
            sys_.add_channel(ch)


class TestAddMemoryRegion:
    def test_add_mr_success(self, sys_):
        mr = MagicMock(name="mr")
        sys_.add_memory_region(mr)
        assert mr in sys_.mrs

    def test_add_duplicate_mr_raises(self, sys_):
        mr = MagicMock(name="mr")
        sys_.add_memory_region(mr)
        with pytest.raises(RuntimeError, match="Cannot add one memory region to the same system multiple times"):
            sys_.add_memory_region(mr)


class TestAddSubsystem:
    def test_add_subsystem_appends(self, sys_):
        ss = make_subsystem()
        sys_.add_subsystem(ss)
        assert sys_.subsystems == [ss]

    def test_add_subsystem_preserves_order(self, sys_):
        ss1, ss2 = make_subsystem(), make_subsystem()
        sys_.add_subsystem(ss1)
        sys_.add_subsystem(ss2)
        assert sys_.subsystems == [ss1, ss2]

    def test_add_subsystem_allows_duplicates(self, sys_):
        # Unlike pds/mrs/channels, subsystems is a plain list with no dedup.
        ss = make_subsystem()
        sys_.add_subsystem(ss)
        sys_.add_subsystem(ss)
        assert sys_.subsystems == [ss, ss]


class TestResolveSubsystems:
    def test_resolve_empty(self, sys_):
        sys_.resolve_subsystems()
        assert sys_.subsystems_constructed is True
        assert sys_.pds == set()

    def test_resolve_calls_build(self, sys_):
        ss = make_subsystem()
        sys_.add_subsystem(ss)
        sys_.resolve_subsystems()
        ss.build.assert_called_once()

    def test_resolve_collects_entities(self, sys_):
        pd = MagicMock(name="pd")
        mr = MagicMock(name="mr")
        ch = MagicMock(name="ch")
        ss = make_subsystem(pds=[pd], mrs=[mr], channels=[ch])
        sys_.add_subsystem(ss)

        sys_.resolve_subsystems()

        assert pd in sys_.pds
        assert mr in sys_.mrs
        assert ch in sys_.channels

    def test_resolve_adds_clients_as_pds(self, sys_):
        client = MagicMock(name="client")
        ss = make_subsystem(clients=[client])
        sys_.add_subsystem(ss)

        sys_.resolve_subsystems()

        assert client in sys_.pds

    def test_resolve_skips_already_installed_client(self, sys_):
        # A client shared between two subsystems must only be added once and
        # must NOT trigger the duplicate-PD RuntimeError.
        client = MagicMock(name="shared_client")
        ss1 = make_subsystem(clients=[client])
        ss2 = make_subsystem(clients=[client])
        sys_.add_subsystem(ss1)
        sys_.add_subsystem(ss2)

        sys_.resolve_subsystems()  # Must not raise

        assert client in sys_.pds

    def test_resolve_client_colliding_with_pd_skipped(self, sys_):
        # If the same object is reported as a PD by one subsystem and a client
        # by another, the client path must skip it rather than re-add.
        shared = MagicMock(name="shared")
        ss1 = make_subsystem(pds=[shared])
        ss2 = make_subsystem(clients=[shared])
        sys_.add_subsystem(ss1)
        sys_.add_subsystem(ss2)

        sys_.resolve_subsystems()  # Must not raise

        assert shared in sys_.pds

    def test_resolve_duplicate_pd_across_subsystems_raises(self, sys_):
        # Two subsystems both reporting the same *non-client* PD is a genuine
        # error and should surface from add_pd.
        pd = MagicMock(name="pd")
        ss1 = make_subsystem(pds=[pd])
        ss2 = make_subsystem(pds=[pd])
        sys_.add_subsystem(ss1)
        sys_.add_subsystem(ss2)

        with pytest.raises(RuntimeError, match="Cannot add one PD"):
            sys_.resolve_subsystems()

    def test_resolve_sets_constructed_flag(self, sys_):
        ss = make_subsystem()
        sys_.add_subsystem(ss)
        sys_.resolve_subsystems()
        assert sys_.subsystems_constructed is True

    def test_resolve_processes_subsystems_in_order(self, sys_):
        order = []
        ss1 = make_subsystem()
        ss2 = make_subsystem()
        ss1.build.side_effect = lambda: order.append("ss1")
        ss2.build.side_effect = lambda: order.append("ss2")
        sys_.add_subsystem(ss1)
        sys_.add_subsystem(ss2)

        sys_.resolve_subsystems()

        assert order == ["ss1", "ss2"]


class TestRender:
    def test_render_returns_system_element(self, sys_):
        root = sys_.render()
        assert isinstance(root, et.Element)
        assert root.tag == "system"

    def test_render_auto_resolves_when_unconstructed(self, sys_):
        ss = make_subsystem()
        sys_.add_subsystem(ss)
        assert sys_.subsystems_constructed is False

        sys_.render()

        ss.build.assert_called_once()
        assert sys_.subsystems_constructed is True

    def test_render_does_not_reresolve_when_constructed(self, sys_):
        ss = make_subsystem()
        sys_.add_subsystem(ss)
        sys_.resolve_subsystems()
        ss.build.reset_mock()

        sys_.render()

        ss.build.assert_not_called()

    def test_render_without_construct_raises(self, sys_):
        # construct_subsystems=False on an unconstructed system is a hard error.
        with pytest.raises(RuntimeWarning, match="without constructing subsystems"):
            sys_.render(construct_subsystems=False)

    def test_render_allocates_and_renders_mrs(self, sys_):
        mr = MagicMock(name="mr")
        sys_.add_memory_region(mr)
        sys_.subsystems_constructed = True  # skip auto-resolve

        root = sys_.render()

        mr.allocate_paddr.assert_called_once_with(sys_.allocator)
        mr.render.assert_called_once_with(root)

    def test_render_renders_pds(self, sys_):
        pd = MagicMock(name="pd")
        sys_.add_pd(pd)
        sys_.subsystems_constructed = True

        root = sys_.render()

        pd.render.assert_called_once_with(root)

    def test_render_renders_channels(self, sys_):
        ch = MagicMock(name="ch")
        sys_.add_channel(ch)
        sys_.subsystems_constructed = True

        root = sys_.render()

        ch.render.assert_called_once_with(root)

    def test_render_renders_all_entities(self, sys_):
        pd, mr, ch = MagicMock(), MagicMock(), MagicMock()
        sys_.add_pd(pd)
        sys_.add_memory_region(mr)
        sys_.add_channel(ch)
        sys_.subsystems_constructed = True

        root = sys_.render()

        mr.render.assert_called_once_with(root)
        pd.render.assert_called_once_with(root)
        ch.render.assert_called_once_with(root)



class TestWriteXmlFile:
    def test_write_xml_file_invokes_render(self, sys_, tmp_path):
        out = tmp_path / "sys.xml"
        with patch.object(sys_, "render", return_value=et.Element("system")) as mock_render:
            sys_.write_xml_file(str(out))
            mock_render.assert_called_once()

    def test_write_xml_file_produces_valid_xml(self, sys_, tmp_path):
        # End-to-end on an empty (but constructed) system: file must parse back.
        sys_.subsystems_constructed = True
        out = tmp_path / "sys.xml"

        sys_.write_xml_file(str(out))

        assert out.exists()
        tree = et.parse(str(out))
        assert tree.getroot().tag == "system"

    def test_write_xml_file_writes_declaration(self, sys_, tmp_path):
        sys_.subsystems_constructed = True
        out = tmp_path / "sys.xml"

        sys_.write_xml_file(str(out))

        content = out.read_text(encoding="utf-8")
        assert content.startswith("<?xml")

