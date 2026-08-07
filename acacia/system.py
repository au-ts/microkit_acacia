# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from __future__ import annotations
import pathlib
import xml.etree.ElementTree as et
from typing import List, Set, Optional
from unittest.mock import MagicMock
from typing import TYPE_CHECKING

from .arch import Arch, ArchID
from .subsystem import Subsystem
from .dtb import DeviceTreeBlob
from .configstruct import ConfigStruct, ConfigStructResolver

# To avoid circular imports, we only do a "real" import when type checking.
if TYPE_CHECKING:
    from acacia.pd import ProtectionDomain
    from acacia.memory import MemoryRegion, Map, IOAddressSpace, IOMap
    from acacia.channel import Channel
    from acacia.configstruct import ConfigStruct


class System:
    """
    A Microkit system.
    """

    def __init__(
        self, sys_arch: Arch, paddr_top: int, dtb: Optional[DeviceTreeBlob] = None
    ):
        self.arch = sys_arch
        self.paddr_top = paddr_top

        # We store sets, not lists. No duplicates allowed!
        self.pds: Set["ProtectionDomain"] = set()
        self.mrs: Set["MemoryRegion"] = set()
        self.channels: Set["Channel"] = set()
        self.io_spaces: Set["IOAddressSpace"] = set()
        self.subsystems: List[Subsystem] = []
        self.system_assembled = False
        self.dtb = dtb

    def _add_pd(self, pd: "ProtectionDomain"):
        self.pds.add(pd)

    def _add_channel(self, channel: "Channel"):
        self.channels.add(channel)

    def _add_memory_region(self, mr: "MemoryRegion"):
        self.mrs.add(mr)

    def _add_io_address_space(self, ios: "IOAddressSpace"):
        self.io_spaces.add(ios)

    def _add_subsystem(self, subsystem: Subsystem):
        self.subsystems.append(subsystem)

    def assemble(self):
        """
        Run all automated connection steps.
        1. Resolve subsystems and connect their clients.
        2. Allocate any memory addresses that are not assigned yet,
        """
        self.resolve_subsystems()
        # allocate AFTER subsystems are built to make sure we don't miss anything
        self.auto_allocate()
        self.system_assembled = True

    def resolve_subsystems(self):
        """
        Construct all subsystems and their client connections.
        """
        for s in self.subsystems:
            if s.built:
                continue
            print(f"Installing {s}...")
            # Build subsystem and record entities
            s.build()
            for client in s.get_clients():
                if client in self.pds:
                    print(f"\tSkipping client {client} which is already installed.")
                else:
                    print(f"\tadding client {client}...")
                    self._add_pd(client)

    def auto_allocate(self):
        """
        Allocate all un-allocated memory and other resources which can be left
        blank for automatic assignment.

        Currently this only handles assigning paddrs to physical memory regions
        without explicit addresses.
        """
        # Filter out any MRs above paddr_top - this is needed for x86 systems, where paddrs can
        # correspond to higher memory than we safely allocate to automatically
        physical_mrs = [
            m
            for m in self.mrs
            if m.physical and (not m.paddr or m.paddr < self.paddr_top)
        ]
        used_range = [m for m in physical_mrs if m.paddr is not None]

        # Sort MRs by name to ensure consistency. Reverse since we pop from end
        to_alloc = sorted(
            [m for m in physical_mrs if m.paddr is None],
            key=lambda m: m.name,
            reverse=True,
        )
        page_size = self.arch.default_page_size()

        while to_alloc:
            mr = to_alloc.pop()
            if mr.size % page_size != 0:
                raise RuntimeError(
                    f"Physical region {mr} has page-unaligned size {mr.size}!"
                )

            # (re)Sort used_range in descending order since we're allocating from top
            used_range = sorted(
                [m for m in physical_mrs if m.paddr is not None],
                key=lambda m: m.paddr,
                reverse=True,
            )

            if len(used_range) != 0:
                # we want to be as close to paddr_top as possible
                prev_page_start = self.paddr_top
                next_paddr = None

                for m in used_range:
                    # Check if we can fit in between the previous page,
                    # ensuring the end address is aligned
                    this_page_end = m.paddr + m.size
                    this_page_end_aligned = this_page_end & ~(page_size - 1)
                    assert this_page_end <= prev_page_start
                    """
                    -----  paddr_top 0x1000_0000 (initial prev_page_start)
                    | b?|
                    |   |
                    |---|  end of a     -> 0x9999_9000
                    | a |                   (0x1000)
                    |---|  start of a   -> 0x9999_8000

                    important: paddrs are allocated from the top down, but MRs are allocated up!
                    we need to see if we can can fit our new mr between the end of the next
                    allocated MR and the prev_page_start.
                    """
                    if prev_page_start >= this_page_end_aligned + mr.size:
                        # fits!
                        next_paddr = prev_page_start - mr.size
                        break
                    # move prev start to the start of this region if we don' fit
                    prev_page_start = m.paddr

                if next_paddr is None:
                    # No suitable gap found, place after the last allocated region's start
                    next_paddr = prev_page_start - mr.size
                    if next_paddr % page_size != 0:
                        next_paddr += next_paddr & ~(page_size - 1)

            else:
                next_paddr = self.paddr_top - mr.size

            # Ensure final address is aligned
            assert next_paddr & ~(page_size - 1) == next_paddr
            if next_paddr < 0:
                raise RuntimeError(
                    f"System has run out of physical memory when allocating {mr}!"
                )
            mr._set_paddr(next_paddr)

    def make_config_structs(self, build_dir: pathlib.Path = pathlib.Path("./")):
        # We can't get config structs without resolving subsystems first
        if not self.system_assembled:
            print("System::make_config_structs - auto-assembling")
            self.assemble()
        # TODO: support big endian?
        resolver = ConfigStructResolver(
            build_dir, endian="little", arch_64_bit=self.arch.is_64_bit()
        )
        for s in self.subsystems:
            resolver.add_structs(s.generate_config_structs())
        resolver.resolve_and_create_all()

    def render(self) -> et.Element:
        if not self.system_assembled:
            print("System::render - auto-assembling")
            self.assemble()
        system = et.Element("system")

        # QoL: sort memory everything by name
        for mr in sorted(self.mrs, key=lambda m: m.name):
            mr.render(system)

        for ios in sorted(self.io_spaces, key=lambda i: i.name):
            ios.render(system)

        for pd in sorted(self.pds, key=lambda p: p.name):
            pd.render(system)

        # Arrange channels by the first PD's name.
        for ch in sorted(self.channels, key=lambda c: c.end_a.pd.name):
            ch.render(system)

        return system

    def write_xml_file(self, path: pathlib.Path):
        xml = self.render()
        et.indent(xml, level=0)

        tree = et.ElementTree(xml)
        et.indent(tree, space="    ", level=0)
        tree.write(path, encoding="utf-8", xml_declaration=True)
