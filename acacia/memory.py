# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Union, Set
from dataclasses import dataclass
import xml.etree.ElementTree as et
from .arch import SDFMemoryAllocator
from .system import System


class MemoryRegion:
    """
    A concrete instance of a memory region. Given that these
    are always absolutely defined, we don't need to support
    and constraint solving ... just need to make sure all defined MRs fit when building the system.

    Microkit will assign paddrs etc. itself, so we don't need to worry about this too much.
    """

    def __init__(
        self,
        sdf: System,
        name: str,
        size: int,
        paddr: Optional[int] = None,
        cached: bool = True,
        physical: bool = False,
    ):
        self.name = name
        if size <= 0:
            raise ValueError("Size must be positive and non-zero!")
        self.size = size
        if paddr is not None:
            physical = True
        self.paddr = paddr
        self.physical = physical
        self.cached = cached
        self.sdf = sdf

        # Allocate ourselves to SDF
        self.sdf._add_memory_region(self)

    def allocate_paddr(self, allocator: SDFMemoryAllocator) -> Optional[int]:
        """
        Allocate a new paddr given the current top pointer.

        Returns:
            int: new paddr_top
        """
        if self.paddr is not None or not self.physical:
            return None  # nothing to do if already assigned or virtual

        self.paddr = allocator.allocate(self.size)
        return self.paddr

    def render(self, system_root: et.Element):
        mr = et.SubElement(system_root, "memory_region")
        mr.set("name", self.name)
        mr.set("size", hex(self.size))
        if self.paddr is not None:
            mr.set("phys_addr", hex(self.paddr))


class Map:
    """
    A mapping of a MemoryRegion into a PD or VM.
    """

    @dataclass(frozen=True)
    class Permissions:
        r: bool = False
        w: bool = False
        x: bool = False

        def __str__(self):
            # "if [r,w,x] in thing, include corresponding char"
            return "".join(
                [e[1] for e in zip([self.r, self.w, self.x], ["r", "w", "x"]) if e[0]]
            )

        def __post_init__(self):
            # Don't let users define write-only pages.
            if not self.r and not self.x and self.w:
                raise ValueError("Cannot define write-only pages!")

    def __init__(
        self,
        mr: MemoryRegion,
        vaddr: int,
        permissions: Union[Permissions, str],
        setvar_vaddr: Optional[str] = None,
    ):
        self.mr = mr

        # Handle instantiating permissions from string
        if type(permissions) is str:
            permissions = permissions.lower()
            # "nothing but r, w, and x please"
            if len(set(permissions).difference((set("rwx")))) != 0:
                raise ValueError(
                    "Only r, w, and x are valid permissions string members!"
                )
            _p = permissions
            permissions = Map.Permissions(r="r" in _p, w="w" in _p, x="x" in _p)
        self.perms = permissions
        self.setvar_vaddr = setvar_vaddr
        self.vaddr = vaddr

    @property
    def size(self):
        return self.mr.size

    def render(self, parent: et.Element) -> et.Element:
        map = et.SubElement(parent, "map")
        map.set("mr", self.mr.name)
        map.set("vaddr", hex(self.vaddr))
        map.set("perms", str(self.perms))
        if not self.mr.cached:
            map.set("cached", "false")
        if self.setvar_vaddr is not None:
            map.set("setvar_vaddr", str(self.setvar_vaddr))
        return map

    @property
    def end_vaddr(self):
        return self.vaddr + self.size


class IOMap:
    """
    Representation of a Microkit io map: a mapping of a MemoryRegion to an IOAddressSpace.
    """

    def __init__(
        self,
        mr: MemoryRegion,
        iovaddr: int,
        allow_reads: bool = True,
        allow_writes: bool = True,
    ):
        self.mr = mr
        self.iovaddr = iovaddr
        self.allow_reads = allow_reads
        self.allow_writes = allow_writes
        if not allow_reads and not allow_writes:
            # Error here to prevent confusing bugs
            raise ValueError("IOMaps cannot be unreadable and unwritable!")

    def render(self, parent: et.Element) -> et.Element:
        iomap = et.SubElement(parent, "iomap")
        iomap.set("mr", self.mr.name)
        iomap.set("iovaddr", hex(self.iovaddr))
        perms_str = "".join(
            [
                e[1]
                for e in zip([self.allow_reads, self.allow_writes], ["r", "w"])
                if e[0]
            ]
        )
        iomap.set("perms", perms_str)
        return iomap


class IOAddressSpace:
    """
    Representation of a Microkit io space (i.e. an IOMMU protected device address space).
    https://docs.sel4.systems/projects/microkit/manual/latest/#io_address_space
    """

    def __init__(self, sdf: System, name: str, peripheral_id: str, domain_id: str):
        self.sdf = sdf
        self.name = name
        self.peripheral_id = peripheral_id
        self.domain_id = domain_id
        self.iomaps: Set[IOMap] = set()
        self.sdf._add_io_address_space(self)

    def add_io_map(self, iomap: IOMap):
        self.iomaps.add(iomap)

    def render(self, system_root: et.Element) -> et.Element:
        ioas = et.SubElement(system_root, "io_address_space")
        ioas.set("name", self.name)
        ioas.set("peripheral_id", self.peripheral_id)
        ioas.set("domain_id", self.domain_id)
        for iomap in self.iomaps:
            iomap.render(ioas)
        return ioas
