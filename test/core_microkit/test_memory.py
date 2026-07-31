# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from unittest.mock import MagicMock
from acacia.memory import MemoryRegion, Map, IOAddressSpace, IOMap
from acacia.arch import aarch64


@pytest.fixture
def sdf():
    """A stand-in System for entity constructors."""
    return MagicMock(name="sdf")


class TestMemoryRegion:
    def test_positive_size_required(self, sdf):
        with pytest.raises(ValueError, match="positive"):
            MemoryRegion(sdf, "test", 0)
        with pytest.raises(ValueError, match="positive"):
            MemoryRegion(sdf, "test", -1)

    def test_paddr_sets_physical(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000, paddr=0x40000000)
        assert mr.physical
        assert mr.paddr == 0x40000000

    def test_no_paddr_virtual(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        assert not mr.physical
        assert mr.paddr is None

    def test_cached_true_default(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        assert mr.cached

    def test_cached_false(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000, cached=False)
        assert not mr.cached

    def test_render(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x2000)
        root = et.Element("system")
        mr.render(root)
        mr_elem = root.find("memory_region")
        assert mr_elem is not None
        assert mr_elem.get("name") == "test_mr"
        assert mr_elem.get("size") == "0x2000"


class TestMapPermissions:
    def test_write_only_rejected(self):
        with pytest.raises(ValueError, match="write-only"):
            Map.Permissions(r=False, w=True, x=False)

    def test_str_representation(self):
        p = Map.Permissions(r=True, w=True, x=False)
        assert str(p) == "rw"
        p = Map.Permissions(r=True, w=False, x=True)
        assert str(p) == "rx"
        p = Map.Permissions(r=False, w=False, x=True)
        assert str(p) == "x"
        p = Map.Permissions(r=True, w=False, x=False)
        assert str(p) == "r"


class TestMap:
    def test_string_permissions_parsing(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        m = Map(mr, 0x40000000, "rwx")
        assert m.perms.r and m.perms.w and m.perms.x

    def test_string_permissions_partial(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        m = Map(mr, 0x40000000, "rw")
        assert m.perms.r and m.perms.w and not m.perms.x

    def test_permissions_string_too_long(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        with pytest.raises(ValueError, match="Only r, w, and x"):
            Map(mr, 0x40000000, "rwxc")

    def test_render_basic(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        m = Map(mr, 0x40000000, "rw")
        parent = et.Element("parent")
        m.render(parent)
        map_elem = parent.find("map")
        assert map_elem.get("mr") == "test_mr"
        assert map_elem.get("vaddr") == "0x40000000"
        assert map_elem.get("perms") == "rw"

    def test_render_cached_false(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x1000)  # cached=False by default
        m = Map(mr, 0x40000000, "rw")
        parent = et.Element("parent")
        m.render(parent)
        map_elem = parent.find("map")
        assert map_elem.get("cached") is None

    def test_render_cached_true_omitted(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x1000, cached=True)
        m = Map(mr, 0x40000000, "rw")
        parent = et.Element("parent")
        m.render(parent)
        map_elem = parent.find("map")
        assert "cached" not in map_elem.attrib

    def test_render_setvar_vaddr(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        m = Map(mr, 0x40000000, "rw", setvar_vaddr="my_vaddr")
        parent = et.Element("parent")
        m.render(parent)
        map_elem = parent.find("map")
        assert map_elem.get("setvar_vaddr") == "my_vaddr"


class TestIOMap:
    def test_unreadable_and_unwritable_rejected(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        with pytest.raises(ValueError, match="unreadable and unwritable"):
            IOMap(mr, 0x40000000, allow_reads=False, allow_writes=False)

    def test_default_permissions_rw(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        iomap = IOMap(mr, 0x40000000)
        assert iomap.allow_reads
        assert iomap.allow_writes

    def test_read_only(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        iomap = IOMap(mr, 0x40000000, allow_writes=False)
        assert iomap.allow_reads
        assert not iomap.allow_writes

    def test_write_only_allowed(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        iomap = IOMap(mr, 0x40000000, allow_reads=False)
        assert not iomap.allow_reads
        assert iomap.allow_writes

    def test_render_rw(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        iomap = IOMap(mr, 0x40000000)
        parent = et.Element("parent")
        iomap.render(parent)
        iomap_elem = parent.find("iomap")
        assert iomap_elem is not None
        assert iomap_elem.get("mr") == "test_mr"
        assert iomap_elem.get("iovaddr") == "0x40000000"
        assert iomap_elem.get("perms") == "rw"

    def test_render_read_only(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        iomap = IOMap(mr, 0x40000000, allow_writes=False)
        parent = et.Element("parent")
        iomap.render(parent)
        iomap_elem = parent.find("iomap")
        assert iomap_elem.get("perms") == "r"

    def test_render_write_only(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        iomap = IOMap(mr, 0x40000000, allow_reads=False)
        parent = et.Element("parent")
        iomap.render(parent)
        iomap_elem = parent.find("iomap")
        assert iomap_elem.get("perms") == "w"


class TestIOAddressSpace:
    def test_construction(self, sdf):
        ioas = IOAddressSpace(sdf, "test_ioas", "0x12345", "0x1")
        assert ioas.name == "test_ioas"
        assert ioas.peripheral_id == "0x12345"
        assert ioas.domain_id == "0x1"
        assert ioas.iomaps == set()

    def test_add_io_map(self, sdf):
        mr = MemoryRegion(sdf, "test", 0x1000)
        iomap = IOMap(mr, 0x40000000)
        ioas = IOAddressSpace(sdf, "test_ioas", "0x12345", "0x1")
        ioas.add_io_map(iomap)
        assert iomap in ioas.iomaps

    def test_render_with_iomaps(self, sdf):
        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        iomap = IOMap(mr, 0x40000000, allow_writes=False)
        ioas = IOAddressSpace(sdf, "test_ioas", "0x12345", "0x1")
        ioas.add_io_map(iomap)
        root = et.Element("system")
        ioas.render(root)
        ioas_elem = root.find("io_address_space")
        assert ioas_elem is not None
        assert ioas_elem.get("name") == "test_ioas"
        assert ioas_elem.get("peripheral_id") == "0x12345"
        assert ioas_elem.get("domain_id") == "0x1"
        iomap_elem = ioas_elem.find("iomap")
        assert iomap_elem is not None
        assert iomap_elem.get("mr") == "test_mr"
        assert iomap_elem.get("iovaddr") == "0x40000000"
        assert iomap_elem.get("perms") == "r"

    def test_render_no_iomaps(self, sdf):
        ioas = IOAddressSpace(sdf, "test_ioas", "0x12345", "0x1")
        root = et.Element("system")
        ioas.render(root)
        ioas_elem = root.find("io_address_space")
        assert ioas_elem is not None
        assert ioas_elem.find("iomap") is None
