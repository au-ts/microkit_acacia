# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as et
from enum import Enum
from typing import TYPE_CHECKING, List, Optional, Set

from .arch import Arch, ArchID
from .configstruct import ConfigStructResolver
from .dtb import DeviceTreeBlob
from .subsystem import Subsystem, SubsystemBuildError

# To avoid circular imports, we only do a "real" import when type checking.
if TYPE_CHECKING:
    from acacia.channel import Channel
    from acacia.memory import IOAddressSpace, MemoryRegion
    from acacia.pd import ProtectionDomain


class AcaciaSystemError(RuntimeError): ...


class SystemState(Enum):
    """
    An Acacia system has a few states which progress linearly in this order:

        Specification : Metaprogram still adding new things / YAML being parsed
        Assembly: All things added, Acacia starts to put together subsystems
        Allocation: Subsystems assembled. Allocate final objects (unassigned paddrs)
        Final: Acacia is done. Calling terminal actions no longer has an effect

    The specication stage is the most permissive, allowing users to manually assign
    sensitive things like map virtual addresses or channel IDs. Manual assignment of
    these properties (used commonly by clients of subsystems) is only safe here, since
    once subsystems build, it must be an invariant that automatic allocation always
    succeeds.

    The assembly state is triggered by calling a *terminal action* (write_xml_file
    or create_config_structs).

    Once in the final state, all subsystems are considered "finished".
    """

    SPECIFICATION = 0
    ASSEMBLY = 1
    ALLOCATION = 2
    FINAL = 3


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
        self.state = SystemState.SPECIFICATION
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
        if self.state != SystemState.SPECIFICATION:
            raise AcaciaSystemError(
                "Cannot add subsystems to System after the specification stage ends!"
            )
        self.subsystems.append(subsystem)

    def assemble(self):
        """
        Run all automated connection steps.
        1. Resolve subsystems and connect their clients.
        2. Allocate any memory addresses that are not assigned yet,
        """

        # Set stage to ASSEMBLY to disable manual specification of vaddrs in memory.py
        # and IDs in pd.py
        self.stage = SystemState.ASSEMBLY
        self.resolve_subsystems()

        # allocate AFTER subsystems are built to make sure we don't miss anything.
        # Set allocation stage ... currently unused.
        self.stage = SystemState.ALLOCATION
        self.auto_allocate()

        # Mark state as FINAL ... we are done!
        self.state = SystemState.FINAL

    def resolve_subsystems(self):
        """
        Construct all subsystems and their client connections.
        """
        for s in self.subsystems:
            try:
                print(f"Installing {s}...")
                if s.built:
                    print("\t...is already installed, skipping")
                    continue
                # Build subsystem and record entities
                s.build()
            except Exception as e:
                raise AcaciaSystemError(f"{s} failed to build!") from e

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
        page_size = self.arch.default_page_size_bytes()

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

    def make_config_structs(
        self, build_dir: pathlib.Path = pathlib.Path("./"), dump: bool = False
    ):
        # We can't get config structs until assembled
        if self.state != SystemState.FINAL:
            self.assemble()
        # TODO: support big endian?
        resolver = ConfigStructResolver(build_dir, endian="little")
        for s in self.subsystems:
            resolver.add_structs(s.generate_config_structs())
        resolver.resolve_and_create_all(dump)

    def render(self) -> et.Element:
        if self.state != SystemState.FINAL:
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

    @property
    def microkit_alloc_allowed(self) -> bool:
        """
        Return True if allocating Microkit objects is allowed.
        I.e. has the system fully finished assembling and has made
        XML or config structs?
        """
        return self.state != SystemState.FINAL

    @property
    def manual_alloc_allowed(self) -> bool:
        """
        Return True if it is safe to manually allocate vaddrs, IDs for channels/irqs/
        ioports/children, etc. or anything else that may conflict with automatic allocation
        when assembling subsystems.

        We only allow these things before the assembly phase as this prevents a lot of complexity.
        We want to be able to eagerly auto-allocate such things when making client connections
        since this removes a lot of possible foot guns.
        """
        return self.state == SystemState.SPECIFICATION

    @property
    def system_assembled(self) -> bool:
        """
        Return true if the assembly stage is completed.
        """
        return not self.state in (SystemState.SPECIFICATION, SystemState.ASSEMBLY)

    def __repr__(self) -> str:
        return (
            f"<acacia.system.System({self.arch}, paddr_top={hex(self.paddr_top)})"
            f" @ {hex(id(self))}>"
        )
