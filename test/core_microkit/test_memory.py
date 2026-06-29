# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from acacia.memory import MemoryRegion, Map
from acacia.arch import SDFMemoryAllocator, aarch64


class TestMemoryRegion:
    def test_positive_size_required(self):
        with pytest.raises(ValueError, match="positive"):
            MemoryRegion("test", 0)
        with pytest.raises(ValueError, match="positive"):
            MemoryRegion("test", -1)

    def test_paddr_sets_physical(self):
        mr = MemoryRegion("test", 0x1000, paddr=0x40000000)
        assert mr.physical
        assert mr.paddr == 0x40000000

    def test_no_paddr_virtual(self):
        mr = MemoryRegion("test", 0x1000)
        assert not mr.physical
        assert mr.paddr is None

    def test_cached_true_default(self):
        mr = MemoryRegion("test", 0x1000)
        assert mr.cached

    def test_cached_false(self):
        mr = MemoryRegion("test", 0x1000, cached=False)
        assert not mr.cached

    def test_render(self):
        mr = MemoryRegion("test_mr", 0x2000)
        root = et.Element("system")
        mr.render(root)
        mr_elem = root.find("memory_region")
        assert mr_elem is not None
        assert mr_elem.get("name") == "test_mr"
        assert mr_elem.get("size") == "0x2000"

    def test_allocate_paddr_assigns(self):
        mr = MemoryRegion("test", 0x1000, physical=True)
        alloc = SDFMemoryAllocator(aarch64, 0x80000000)
        mr.allocate_paddr(alloc)
        assert mr.paddr == 0x7ffff000  # 0x80000000 - 0x1000

    def test_allocate_paddr_already_assigned(self):
        mr = MemoryRegion("test", 0x1000, paddr=0x40000000)
        alloc = SDFMemoryAllocator(aarch64, 0x80000000)
        # Should return without error or modification
        mr.allocate_paddr(alloc)
        assert mr.paddr == 0x40000000

    def test_allocate_paddr_virtual_noop(self):
        mr = MemoryRegion("test", 0x1000)  # Not physical
        alloc = SDFMemoryAllocator(aarch64, 0x80000000)
        mr.allocate_paddr(alloc)
        assert mr.paddr is None


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
    def test_invalid_vaddr(self):
        mr = MemoryRegion("test", 0x1000)
        with pytest.raises(ValueError, match="Invalid virtual address"):
            Map(mr, 0, "rw")
        with pytest.raises(ValueError, match="Invalid virtual address"):
            Map(mr, -1, "rw")

    def test_string_permissions_parsing(self):
        mr = MemoryRegion("test", 0x1000)
        m = Map(mr, 0x40000000, "rwx")
        assert m.perms.r and m.perms.w and m.perms.x

    def test_string_permissions_partial(self):
        mr = MemoryRegion("test", 0x1000)
        m = Map(mr, 0x40000000, "rw")
        assert m.perms.r and m.perms.w and not m.perms.x

    def test_permissions_string_too_long(self):
        mr = MemoryRegion("test", 0x1000)
        with pytest.raises(RuntimeError, match="Permissions string"):
            Map(mr, 0x40000000, "rwxc")

    def test_render_basic(self):
        mr = MemoryRegion("test_mr", 0x1000)
        m = Map(mr, 0x40000000, "rw")
        parent = et.Element("parent")
        m.render(parent)
        map_elem = parent.find("map")
        assert map_elem.get("mr") == "test_mr"
        assert map_elem.get("vaddr") == "0x40000000"
        assert map_elem.get("perms") == "rw"

    def test_render_cached_false(self):
        mr = MemoryRegion("test_mr", 0x1000)  # cached=False by default
        m = Map(mr, 0x40000000, "rw")
        parent = et.Element("parent")
        m.render(parent)
        map_elem = parent.find("map")
        assert map_elem.get("cached") is None

    def test_render_cached_true_omitted(self):
        mr = MemoryRegion("test_mr", 0x1000, cached=True)
        m = Map(mr, 0x40000000, "rw")
        parent = et.Element("parent")
        m.render(parent)
        map_elem = parent.find("map")
        assert "cached" not in map_elem.attrib

    def test_render_setvar_vaddr(self):
        mr = MemoryRegion("test_mr", 0x1000)
        m = Map(mr, 0x40000000, "rw", setvar_vaddr="my_vaddr")
        parent = et.Element("parent")
        m.render(parent)
        map_elem = parent.find("map")
        assert map_elem.get("setvar_vaddr") == "my_vaddr"
