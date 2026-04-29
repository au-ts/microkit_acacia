# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import List, Set, Optional
from .arch import Arch, ArchID, SDFMemoryAllocator
from .pd import ProtectionDomain
from .channel import Channel
from .memory import MemoryRegion, Map
from .subsystem import Subsystem, get_dependency_map
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
        # We only support one instance of a subsystem at a time currently.
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
        if type(subsystem) in [type(s) for s in self.subsystems]:
            raise NotImplementedError("Multiple copies of subsystems are not currently supported")
        self.subsystems.append(subsystem)

    def resolve_subsystems(self, auto_build_external_deps=False):
        """
        Construct all subsystems and their client connections. This method
        builds a dependency graph, topologically sorts it, and then
        connects dependencies one at a time. This method will assert
        that all dependencies are of strictly ascending priority order.

        Subsystems are built from highest priority to lowest priority.
        """
        # of highest dependency order first.
        ss_types = [type(x) for x in self.subsystems]

        # Top sort returns a list of types, not class objects.
        top_sorted = [x for x in get_dependency_map().topological_sort(filter=ss_types)]
        subsystem_list = self.subsystems.copy()

        # match top sort output to classes we have. if there are more types
        # in the top sort than the input, the topological sort found external
        # dependencies! (i.e. the user didn't provide instances of a required
        # dependency).
        if len(top_sorted) > len(ss_types):
            if not auto_build_external_deps:
                raise RuntimeError("Subsystem graph has external dependencies!")
            # Construct instances of external deps
            # TODO: this. This won't be that simple, since configuring drivers
            # with things like notification IDs etc. can get complex. Will come
            # back to this later.
            # TODO: amend subsystem_list with new instances
            raise NotImplementedError("pysdfgen cannot handle automatic external deps yet!")

        else:
            expected_cnt = len(subsystem_list)
            # Map types to instances and build!
            ss_to_build = []

            # Sort in order of topological sort with dumb(ish) insertion sort.
            # This should still get O(n log n) due to shortening the list.
            for t in top_sorted:
                victim = None
                for ss in range(len(subsystem_list)):
                    if type(subsystem_list[ss]) == t:
                        victim = ss
                        break
                # This will error if no victim is found... on purpose!
                ss_to_build.append(subsystem_list.pop(victim))

            # Make sure all items were sorted in
            assert len(ss_to_build) == expected_cnt

        # TODO: handle forced max priorities
        min_prio = max([x.priority for x in self.pds])+1 if len(self.pds) > 0 else 0
        for s in ss_to_build:
            print(f"Installing {s} with priority min={min_prio}...")
            # Collect dependencies list and match to instances
            dep_types = get_dependency_map().dep_map[type(s)]
            deps = {}
            for d in dep_types:
                deps[d] = next(x for x in ss_to_build if type(x) == d)

            # Build subsystem and record entities
            min_prio = s.build(min_prio, deps) +1
            for pd in s.get_pds():
                print(f"\tadding pd {pd}...")
                self.add_pd(pd)
            for mr in s.get_mrs():
                print(f"\tadding mr {mr}...")
                self.add_mr(mr)
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
