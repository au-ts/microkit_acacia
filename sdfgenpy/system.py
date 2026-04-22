# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import List, Set, Optional
from .arch import Arch, ArchID, SDFMemoryAllocator
from .pd import ProtectionDomain
from .channel import Channel
from .memory import MemoryRegion, Map
import xml.etree.ElementTree as et

class System:
    """
    A Microkit system.
    """
    def __init__(self, sys_arch: Arch, paddr_top: int):
        self.arch = sys_arch
        self.allocator = SDFMemoryAllocator(sys_arch, paddr_top, sys_arch.default_page_size())

        # We store sets, not lists. No duplicates allowed!
        self.pds: Set[PD] = set()
        self.mrs: Set[MemoryRegion] = set()
        self.channels: Set[Channel] = set()
        self.subsystems = [] #todo

    def add_pd(self, pd: ProtectionDomain):
        # We technically don't need to raise this error, but it's better to
        # alert the user. Sets silently drop duplicates by default.
        if pd in self.pds:
            raise RuntimeError("Cannot add one PD to the same system multiple times!")
        self.pds.add(pd)

    def add_channel(self, channel: Channel):
        if channel in self.channels:
            raise RuntimeError("Cannot add one channel to the same system multiple times!")
        self.channels.add(channel)

    def add_memory_region(self, mr: MemoryRegion):
        if mr in self.mrs:
            raise RuntimeError("Cannot add one memory region to the same system multiple times!")
        self.mrs.add(mr)

    def render(self) -> et.Element:
        system = et.Element("system")

        for mr in self.mrs:
            # Allocate paddr if needed
            mr.allocate_paddr(self.allocator)
            mr.render(system)

        for pd in self.pds:
            pd.render(system)

        for ch in self.channels:
            ch.render(system)


        return system
