# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Union, Set, List, Tuple
from dataclasses import dataclass
import xml.etree.ElementTree as et
from .system import System
from .arch import PageSizeID, Arch
import pathlib
from enum import Enum
import os


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
        size: Optional[int] = None,
        *, 
        paddr: Optional[int] = None,
        cached: bool = True,
        physical: bool = False,
        prefill_bootinfo: Optional[str] = None,
        prefill_path: Optional[pathlib.Path] = None,
    ):
        self.name = name
        if size is not None and size <= 0:
            raise ValueError("Size must be positive and non-zero!")
        if size is None and prefill_bootinfo is None and prefill_path is None:
            raise ValueError("One of [size, prefill_bootinfo, prefill_path] must be set!")

        self.size = size

        if size is None and prefill_path is not None:
            # Find the size of the file in bytes.
            assert pathlib.Path(prefill_path).resolve().exists()
            page_size = sdf.arch.get_page_size(PageSizeID.small)
            file_size = os.path.getsize(prefill_path)
            self.size = (file_size//page_size + 1) * page_size

        if paddr is not None:
            physical = True
        self.paddr = paddr
        self.physical = physical
        self.cached = cached
        self.sdf = sdf
        self.prefill_bootinfo = prefill_bootinfo
        self.prefill_path = prefill_path

        # Allocate ourselves to SDF
        self.sdf._add_memory_region(self)

    def _set_paddr(self, paddr: int) -> Optional[int]:
        """
        Set the paddr for this MR if it wasn't set already.
        """
        assert paddr >= 0
        if self.paddr is not None:
            return None  # nothing to do if already assigned or virtual
        if not self.physical:
            raise RuntimeError("Cannot set paddr on a virtual MemoryRegion!")

        self.paddr = paddr
        return self.paddr

    def render(self, system_root: et.Element):
        mr = et.SubElement(system_root, "memory_region")
        mr.set("name", self.name)
        if self.size is not None:
            mr.set("size", hex(self.size))
        if self.paddr is not None:
            mr.set("phys_addr", hex(self.paddr))
        if self.prefill_bootinfo is not None:
            mr.set("prefill_bootinfo", self.prefill_bootinfo)
        if self.prefill_path is not None:
            mr.set("prefill_path", str(self.prefill_path))



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
        setvar_size: Optional[str] = None,
        setvar_prefill_size: Optional[str] = None,
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
        self.setvar_size = setvar_size
        self.setvar_prefill_size = setvar_prefill_size
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
        if self.setvar_size is not None:
            map.set("setvar_size", self.setvar_size)
        if self.setvar_prefill_size is not None:
            map.set("setvar_prefill_size", self.setvar_prefill_size)
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

class PageTables:
    def __init__(self, setvar:str):
        self.setvar = setvar
        self.pds: List[str] = []
        self.ids: List[int] = []

    def add_entry(self, pd_name: str, index: Optional[int] = None):
        id = index if index is not None else next(i for i in range(63) if i not in self.ids)
        if id in self.ids:
            raise ValueError(f"Failed to add {pd_name} to index {index}: duplicated index")
        self.pds.append(pd_name)
        self.ids.append(id)

    def render(self, parent: et.Element, elem_name: str = "page_tables"):
        entity = et.SubElement(parent, elem_name);
        entity.set("setvar", self.setvar) 
        for (pd, id) in zip(self.pds, self.ids):
            subtable = et.SubElement(entity, "pd")
            subtable.set("name", pd)
            subtable.set("index", str(id))

        return entity

class Cap(Enum):
    SchedCtxt = "sc"
    TCB = "tcb"
    VSpace = "vspace"

class CSpace:
    def __init__(self):
        self.caps: List[Tuple[Cap, int, str]] = []
        self.used_indices: Set[int] = set()

    def add_cap(self, cap: Cap, slot: int, pd_name: str):
        if slot in self.used_indices:
            raise ValueError(f"Duplicate slot {slot}")
        self.caps.append((cap, slot, pd_name))

    def render(self, parent: et.Element, elem_name: str = "cspace"):
        cspace = et.SubElement(parent, elem_name)
        for cap in self.caps:
            cap_elem = et.SubElement(cspace, f"cap_{cap[0].value}")
            cap_elem.set("slot", str(cap[1]))
            cap_elem.set("pd", cap[2])
        return cspace
