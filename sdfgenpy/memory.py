# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Union
from dataclasses import dataclass
import xml.etree.ElementTree as et
from .arch import SDFMemoryAllocator

class MemoryRegion:
    """
    A concrete instance of a memory region. Given that these
    are always absolutely defined, we don't need to support
    and constraint solving ... just need to make sure all defined MRs fit when building the system.

    Microkit will assign paddrs etc. itself, so we don't need to worry about this too much.
    """
    def __init__(self,
                 name: str,
                 size: int,
                 paddr: Optional[int] = None,
                 cached: bool = False,
                 physical: bool = False):
        self.name = name
        if size <= 0:
            raise ValueError("Size must be positive and non-zero!")
        self.size = size
        if paddr is not None:
            physical = True
        self.paddr = paddr
        self.physical = physical
        self.cached = cached

    def allocate_paddr(self, allocator: SDFMemoryAllocator) -> int:
        """
        Allocate a new paddr given the current top pointer.

        Returns:
            int: new paddr_top
        """
        if self.paddr is not None or not self.physical:
            return # nothing to do if already assigned or virtual

        paddr_top = allocator.paddr_top
        self.paddr = paddr_top - self.size
        allocator.update_paddr_top(self.paddr)

    def render(self, system_root: et.Element) -> et.Element:
        mr = et.SubElement(system_root, "memory_region")
        mr.set("name", self.name)
        mr.set("size", hex(self.size))


class Map:
    @dataclass(frozen=True)
    class Permissions:
        r: bool = False
        w: bool = False
        x: bool = False
        def __str__(self):
            return "".join([e[1] for e in
                zip([self.r, self.w, self.x], ['r', 'w', 'x']) if e[0]])

        def __post_init__(self):
            # Don't let users define write-only pages.
            if not self.r and not self.x and self.w:
                raise ValueError("Cannot define write-only pages!")


    """
    A mapping of a MemoryRegion into a PD or VM.
    """
    def __init__(self,
                 mr: MemoryRegion,
                 vaddr: int,
                 permissions: Union[Permissions, str],
                 setvar_vaddr: Optional[str] = None):
        if vaddr <= 0:
            raise ValueError(f"Invalid virtual address {vaddr}!")
        self.mr = mr

        # Handle instantiating permissions from string
        if type(permissions) is str:
            if len(permissions) > 3:
                raise RuntimeError("Permissions string must be <= 3 chars long.")
            _p = permissions
            permissions = Map.Permissions(r='r' in _p, w='w' in _p, x='x' in _p)
        self.perms = permissions
        self.setvar_vaddr = setvar_vaddr
        self.vaddr = vaddr

    def render(self, parent: et.Element) -> et.Element:
        map = et.SubElement(parent, "map")
        map.set("mr", self.mr.name)
        map.set("vaddr", hex(self.vaddr))
        map.set("perms", str(self.perms))
        if not self.mr.cached:
            map.set("cached", "false")
        if self.setvar_vaddr is not None:
            map.set("setvar_vaddr",  str(self.setvar_vaddr))
        return map



