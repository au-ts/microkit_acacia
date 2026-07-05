# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from __future__ import annotations
import pathlib
import xml.etree.ElementTree as et
from typing import List, Set, Optional
from unittest.mock import MagicMock
from typing import TYPE_CHECKING

from .arch import Arch, ArchID, SDFMemoryAllocator
from .subsystem import Subsystem
from .dtb import DeviceTreeBlob
from .configstruct import ConfigStruct, ConfigStructResolver

# To avoid circular imports, we only do a "real" import when type checking.
if TYPE_CHECKING:
    from acacia.pd import ProtectionDomain
    from acacia.memory import MemoryRegion, Map
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
        self.allocator = SDFMemoryAllocator(sys_arch, paddr_top)

        # We store sets, not lists. No duplicates allowed!
        self.pds: Set["ProtectionDomain"] = set()
        self.mrs: Set["MemoryRegion"] = set()
        self.channels: Set["Channel"] = set()
        self.subsystems: List[Subsystem] = []
        self.subsystems_constructed = False
        self.dtb = dtb

    def _add_pd(self, pd: "ProtectionDomain"):
        self.pds.add(pd)

    def _add_channel(self, channel: "Channel"):
        self.channels.add(channel)

    def _add_memory_region(self, mr: "MemoryRegion"):
        self.mrs.add(mr)

    def _add_subsystem(self, subsystem: Subsystem):
        self.subsystems.append(subsystem)

    def resolve_subsystems(self):
        """
        Construct all subsystems and their client connections.
        """
        for s in self.subsystems:
            print(f"Installing {s}...")
            # Build subsystem and record entities
            s.build()
            for client in s.get_clients():
                if client in self.pds:
                    print(f"\tSkipping client {client} which is already installed.")
                else:
                    print(f"\tadding client {client}...")
                    self._add_pd(client)

        self.subsystems_constructed = True

    def make_config_structs(self, build_dir: pathlib.Path = pathlib.Path("./")):
        # We can't get config structs without resolving subsystems first
        if not self.subsystems_constructed:
            print("System::make_config_structs - auto-resolving systems")
            self.resolve_subsystems()
        # TODO: support big endian?
        resolver = ConfigStructResolver(build_dir, endian="little")
        for s in self.subsystems:
            resolver.add_structs(s.generate_config_structs())
        resolver.resolve_and_create_all()

    def render(self) -> et.Element:
        if not self.subsystems_constructed:
            print("System::render - auto-resolving subsystems")
            self.resolve_subsystems()
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

    def write_xml_file(self, path: pathlib.Path):
        xml = self.render()
        et.indent(xml, level=0)

        tree = et.ElementTree(xml)
        et.indent(tree, space="    ", level=0)
        tree.write(path, encoding="utf-8", xml_declaration=True)
