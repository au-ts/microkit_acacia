# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import List, Set, Optional
from .arch import Arch, ArchID, SDFMemoryAllocator
from .pd import ProtectionDomain
from .channel import Channel
from .memory import MemoryRegion, Map
from .subsystem import Subsystem
from .dtb import DeviceTreeBlob
from .configstruct import ConfigStruct, ConfigStructResolver
import xml.etree.ElementTree as et
from unittest.mock import MagicMock
class System:
    """
    A Microkit system.
    """
    def __init__(self, sys_arch: Arch, paddr_top: int, dtb: DeviceTreeBlob=None):
        self.arch = sys_arch
        self.allocator = SDFMemoryAllocator(sys_arch, paddr_top)

        # We store sets, not lists. No duplicates allowed!
        self.pds: Set[ProtectionDomain] = set()
        self.mrs: Set[MemoryRegion] = set()
        self.channels: Set[Channel] = set()
        self.subsystems: List[Subsystem] = []
        self.subsystems_constructed = False
        self.dtb = dtb

    def __system_subclass_check(self, to_check, expected_type):
        if isinstance(to_check, MagicMock):
            # sort of a hack ... ignore mocks used by unit tests.
            return

        if not isinstance(to_check, expected_type):
            raise RuntimeError(f"Tried to add {to_check} as a {expected_type}, "\
                               f"but it is a {type(to_check)}!")

    def add_pd(self, pd: ProtectionDomain):
        # We technically don't need to raise this error, but it's better to
        # alert the user. Sets silently drop duplicates by default.
        self.__system_subclass_check(pd, ProtectionDomain)
        if pd in self.pds:
            raise RuntimeError("Cannot add one PD to the same system multiple times!")
        self.pds.add(pd)

    def add_channel(self, channel: Channel):
        self.__system_subclass_check(channel, Channel)
        if channel in self.channels:
            raise RuntimeError("Cannot add one channel to the same system multiple times!")
        self.channels.add(channel)

    def add_memory_region(self, mr: MemoryRegion):
        self.__system_subclass_check(mr, MemoryRegion)
        if mr in self.mrs:
            raise RuntimeError("Cannot add one memory region to the same system multiple times!")
        self.mrs.add(mr)

    def add_subsystem(self, subsystem: Subsystem):
        self.__system_subclass_check(subsystem, Subsystem)
        self.subsystems.append(subsystem)

    def resolve_subsystems(self):
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

    def make_config_structs(self, build_dir: str="./"):
        # We can't get config structs without resolving subsystems first
        if not self.subsystems_constructed:
            print("System::make_config_structs - auto-resolving systems")
            self.resolve_subsystems()
        # TODO: support big endian?
        resolver = ConfigStructResolver(build_dir, endian='little')
        for s in self.subsystems:
            resolver.add_structs(s.generate_config_structs())
        resolver.resolve_all()


    def render(self, construct_subsystems=True) -> et.Element:
        if construct_subsystems and not self.subsystems_constructed:
            print("System::render - auto-resolving subsystems")
            self.resolve_subsystems()
        elif not construct_subsystems:
            raise RuntimeWarning("Tried to render system without constructing subsystems!")
        system = et.Element("system")

        # QoL: sort memory everything by name
        for mr in sorted(self.mrs, key=lambda m: m.name):
            # Allocate paddr if needed
            mr.allocate_paddr(self.allocator)
            mr.render(system)

        for pd in sorted(self.pds, key=lambda p: p.name):
            pd.render(system)

        # Arrange channels by the first PD's name.
        for ch in sorted(self.channels, key=lambda c: c.end_a.pd.name):
            ch.render(system)

        return system

    def write_xml_file(self, path):
        xml = self.render()
        et.indent(xml, level=0)

        tree = et.ElementTree(xml)
        et.indent(tree, space='    ', level=0)
        tree.write(path, encoding="utf-8", xml_declaration=True)
