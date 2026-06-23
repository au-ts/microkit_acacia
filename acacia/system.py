# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import List, Set, Optional
from .arch import Arch, ArchID, SDFMemoryAllocator
from .pd import ProtectionDomain
from .channel import Channel
from .memory import MemoryRegion, Map
from .subsystem import Subsystem
import xml.etree.ElementTree as et

class System:
    """
    A Microkit system.
    """
    def __init__(self, sys_arch: Arch, paddr_top: int):
        self.arch = sys_arch
        self.allocator = SDFMemoryAllocator(sys_arch, paddr_top, sys_arch.default_page_size())

        # We store sets, not lists. No duplicates allowed!
        self.pds: Set[ProtectionDomain] = set()
        self.mrs: Set[MemoryRegion] = set()
        self.channels: Set[Channel] = set()
        self.subsystems: List[Subsystem] = []
        self.subsystems_constructed = False

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

    def add_subsystem(self, subsystem: Subsystem):
        self.subsystems.append(subsystem)

    def resolve_subsystems(self, auto_build_external_deps=False):
        """
        Construct all subsystems and their client connections.
        """
        for s in self.subsystems:
            print(f"Installing {s}...")
            # Build subsystem and record entities
            s.build()
            for pd in s.get_pds():
                print(f"\tadding pd {pd}...")
                self.add_pd(pd)
            for mr in s.get_mrs():
                print(f"\tadding mr {mr}...")
                self.add_memory_region(mr)
            for channel in s.get_channels():
                print(f"\tadding ch {channel}...")
                self.add_channel(channel)
            for client in s.get_clients():
                if client in self.pds:
                    print(f"\tSkipping client {client} which is already installed.")
                else:
                    print(f"\tadding client {client}...")
                    self.add_pd(client)

        self.subsystems_constructed = True


    def render(self, construct_subsystems=True) -> et.Element:
        if construct_subsystems and not self.subsystems_constructed:
            print("System::render - auto-resolving subsystems")
            self.resolve_subsystems()
        elif not construct_subsystems:
            raise RuntimeWarning("Tried to render system without constructing subsystems!")
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

    def write_xml_file(self, path):
        xml = self.render()
        et.indent(xml, level=0)

        tree = et.ElementTree(xml)
        et.indent(tree, space='\t', level=0)
        tree.write(path, encoding="utf-8", xml_declaration=True)
