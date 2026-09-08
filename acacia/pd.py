# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Set, Union, List, Sequence
from dataclasses import dataclass
from abc import ABC
import xml.etree.ElementTree as et
from .system import System
from .memory import MemoryRegion, Map, PageTables, CSpace
from .irq import IRQ
from .x86 import IOPort

MAX_IDS = 62  # matches microkit. limit for child pds, ioports, irqs and channel IDs


@dataclass
class SchedulingProperties:
    """
    Properties of an entity for the seL4 scheduler
    """

    # priority: Union[int, FieldSpec[int]]
    priority: int
    period: Optional[int] = None
    budget: Optional[int] = None
    passive: bool = False

    def __post_init__(self):
        # Enforce sane values
        if self.priority is None or self.priority < 0:
            raise ValueError("Must define a non-negative priority!")

        # If we have a period, we must also have a budget, and the budget must be
        # larger than (or equal to) the period
        if self.period is not None:
            if self.budget is None or self.budget > self.period:
                raise ValueError(
                    "Budget must be defined and cannot be greater than period!"
                )


class Entity:
    """
    An executing entity. I.e. a PD or VM, or anything else that appears
    in future which:
        a. has scheduling paramters
        b. can be targeted by maps
    """

    def __init__(
        self,
        name: str,
        scheduling: Optional[SchedulingProperties],
        map_start_vaddr: int = 0x20_000_000,
    ):
        self.name = name.strip()
        self.scheduling = scheduling
        self.maps: List[Map] = []
        self.map_start_vaddr = map_start_vaddr

    @property
    def priority(self):
        return self.scheduling.priority if self.scheduling is not None else None

    @property
    def budget(self):
        return self.scheduling.budget if self.scheduling is not None else None

    @property
    def period(self):
        return self.scheduling.period if self.scheduling is not None else None

    def add_map(self, map: Map):
        self.maps.append(map)

    def create_automap(
        self,
        mr: MemoryRegion,
        perms: Union[Map.Permissions, str],
        page_size=0x1000,
    ) -> Map:
        """
        Given a memory region, automatically create a map and assign it a vaddr
        that doesn't overlap with any existing maps.

        Args:
            mr: MemoryRegion to map
            perms: Map permissions - read, write, execute
            start_vaddr: lowest address to auto-allocate map. Default: 0x20_000_000
            page_size: page size used. Defaults to 0x1000.

        Returns:
            Map: created map object.

        NOTE: This replaces `getMapVaddr` in zig sdfgen.
        """
        if len(self.maps) != 0:
            # python sorted() is adaptive, so this doesn't waste much time on repeats!
            self.maps = sorted(self.maps, key=lambda m: m.vaddr)

            # We now want to find a good gap. I.e.
            # a) we want to be as close to start_vaddr as possible
            # b) we want to preserve guard pages between mappings
            # NOTE: we could accelerate this by remembering continguously allocated ranges.
            prev_guard_page_end = self.map_start_vaddr
            for m in self.maps:
                # If the space between the previous end and this start is big enough to fit
                # our new map AND a guard page on either side, accept it.
                if prev_guard_page_end + mr.size + page_size < m.vaddr:
                    # Fits!
                    break
                prev_guard_page_end = m.end_vaddr + page_size

            # Align address to page boundary
            next_vaddr = (prev_guard_page_end + page_size - 1) & ~(page_size - 1)

            # Add space for a guard page, unless we are still at the start
            if next_vaddr != self.map_start_vaddr:
                next_vaddr += page_size
        else:
            next_vaddr = self.map_start_vaddr

        m = Map(mr, next_vaddr, perms)
        self.add_map(m)
        return m

    def render(self, parent: et.Element, elem_name: str):
        entity = et.SubElement(parent, elem_name)
        entity.set("name", str(self.name))
        if self.scheduling is None:
            raise RuntimeError(
                "Cannot render an entity without a SchedulingProperties!"
            )

        entity.set("priority", str(self.priority))
        # Only add passive bool if true
        if self.scheduling.passive:
            entity.set("passive", "true")
        if self.period is not None:
            entity.set("period", str(self.period))
        if self.budget is not None:
            entity.set("budget", str(self.budget))

        # Render maps in ascending order of vaddr
        for map in sorted(self.maps, key=lambda m: m.vaddr):
            map.render(entity)

        return entity


class VirtualMachine(Entity):
    """
    An instance of a VM belonging to a PD. This inherits from entity as
    VMs can be targeted with maps and has scheduling parameters.
    """

    @dataclass
    class VCPU:
        id: int
        cpu: Optional[int] = None

        def __post_init__(self):
            if self.id is None or self.id < 0 or self.id > MAX_IDS:
                raise RuntimeError(f"VCPU ID={self.id} is invalid!")

        def render(self, parent: et.Element):
            entity = et.SubElement(parent, "vcpu")
            entity.set("id", str(self.id))
            if self.cpu is not None:
                entity.set("cpu", str(self.cpu))

    def __init__(
        self,
        name: str,
        vcpus: Sequence[VCPU],
        scheduling: Optional[SchedulingProperties] = None,
    ):
        super().__init__(name, scheduling)
        # Check all IDs are unique
        ids = [x.id for x in vcpus]
        if len(ids) != len(set(ids)):
            raise RuntimeError("All VCPU IDs must be unique per VM!")
        if len(ids) > MAX_IDS:
            raise RuntimeError(f"{MAX_IDS} VCPUs are supported at max!")
        # This is a pointless line to get around mypy checks
        self.vcpus = vcpus

    def render(
        self, parent: et.Element, elem_name: str = "virtual_machine"
    ) -> et.Element:
        vm = super().render(parent, elem_name)
        for vcpu in self.vcpus:
            vcpu.render(vm)
        return vm


class ProtectionDomain(Entity):
    """
    A PD running native code
    """

    def __init__(
        self,
        sdf: System,
        name: str,
        prog_image: str,
        stack_size: Optional[int] = None,
        cpu: Optional[int] = None,
        smc: bool = False,
        scheduling: Optional[SchedulingProperties] = None,
        priority: Optional[int] = None,
    ):
        # This is here to prevent mypy from freaking out over optionals
        actual_scheduling = None
        # We offer `priority=x` as a legacy feature
        if priority is not None:
            if scheduling is not None:
                raise RuntimeError(
                    "Cannot define a SchedulingCharacteristics and priority separately!"
                )
            actual_scheduling = SchedulingProperties(priority)
        else:
            actual_scheduling = scheduling
        super().__init__(name, actual_scheduling)
        if not prog_image.endswith(".elf"):
            raise ValueError("Non-elf program image!")
        self.prog_image = prog_image
        self.stack_size = stack_size
        self.cpu = cpu
        self.smc = smc
        self.irqs: Set[IRQ] = set()
        self.vpmus: Set[int] = set()
        self.ioports: List[IOPort] = []
        self.sdf = sdf
        self.cspaces: List[CSpace] = []
        self.replys: Set[int] = set()

        # Parental responsibilities
        self.children: List[ProtectionDomain] = []
        self.child_id = None  # Assigned if this PD is made a child.

        # VM
        self.vms: List[VirtualMachine] = []
        self.pagetables: List[PageTables] = []

        # Allocate ourselves to SDF
        self.sdf._add_pd(self)

    def render(self, parent: et.Element, elem_name: str = "protection_domain"):
        pd = super().render(parent, elem_name)
        prog_image = et.SubElement(pd, "program_image")
        prog_image.set("path", self.prog_image)

        if self.child_id is not None:
            # If we are a child, include id.
            pd.set("id", str(self.child_id))

        # Only insert stack size, CPU and SMC if defined
        # QoL: render elements in name/val order
        if self.stack_size is not None:
            pd.set("stack_size", str(self.stack_size))
        if self.cpu is not None:
            pd.set("cpu", str(self.cpu))
        if self.smc:
            pd.set("smc", "true")

        for i in sorted(self.irqs, key=lambda ir: ir.id or 0):
            i.render(pd)
        for iop in sorted(self.ioports, key=lambda i: i.addr):
            iop.render(pd)
        for c in sorted(self.children, key=lambda c: c.name):
            c.render(pd)
        for vm in self.vms:
            vm.render(pd)

        for id in self.vpmus:
            et.SubElement(pd, "vpmu").set("virq_id", str(id))

        for pts in self.pagetables:
            pts.render(pd)

        for cspace in self.cspaces:
            cspace.render(pd)

        for reply in self.replys:
            et.SubElement(pd, "reply").set("reply_id", str(reply))

        return pd

    def allocate_id(self, requested_id: Optional[int] = None):
        """
        Allocate an ID (or test a requested id) for a channel or IRQ.
        """
        allocated_irq_ids = [irq.id for irq in self.irqs if irq.id is not None]
        allocated_ch_ids = [
            end.ch_id
            for ch in self.sdf.channels
            for end in (ch.end_a, ch.end_b)
            if end.pd is self and end.ch_id is not None
        ]
        assigned_ids: List[int] = sorted(allocated_ch_ids + allocated_irq_ids)

        if requested_id is not None:
            print(f"WARNING: Assuming requested id is correct!!!")
            return requested_id
            # if requested_id not in assigned_ids:
            #     return requested_id
            # else:
            #     raise RuntimeError("Requested ID is not available!")

        new_id = next(i for i in range(MAX_IDS) if i not in assigned_ids)
        return new_id

    def add_irq(self, irq: IRQ):
        if irq in self.irqs:
            raise RuntimeError("Cannot add the same IRQ to a PD twice!")

        irq.id = self.allocate_id(irq.id)  # Allocate and reserve ID
        self.irqs.add(irq)
        return irq.id

    def add_ioport(self, ioport: IOPort):
        desired_id = ioport.id
        assigned_ids = [iop.id for iop in self.ioports]
        if desired_id is None:
            new_id = next(i for i in range(MAX_IDS) if i not in assigned_ids)
        else:
            if desired_id not in assigned_ids:
                new_id = desired_id
            else:
                raise RuntimeError(f"IOPort ID {desired_id} is unavailable!")
        ioport.id = new_id
        self.ioports.append(ioport)

    def add_child_pd(self, child, child_id: Optional[int] = None):
        if child in self.children:
            raise RuntimeError("Cannot make the same PD a child multiple times!")
        assigned_ids = [child.child_id for child in self.children]
        if child_id is None:
            new_child_id = next(i for i in range(MAX_IDS) if i not in assigned_ids)
        else:
            if child_id not in assigned_ids:
                new_child_id = child_id
            else:
                raise RuntimeError(f"Child ID {child_id} is unavailable!")
        # remove child from sdf.
        self.sdf.pds.remove(child)
        child.child_id = new_child_id
        self.children.append(child)

    def add_vm(self, vm: VirtualMachine):
        assert isinstance(vm, VirtualMachine)
        # If we are targeting x86, scheduling properties are not allowed. We also can only have one
        # VM on x86, but other platforms allow more.
        if self.sdf.arch.is_x86():
            if vm.scheduling is not None:
                raise ValueError("VMs do not support scheduling properties on x86!")
            if len(self.vms) > 0:
                raise ValueError("x86 systems do not support multiple VMs per PD!")
        self.vms.append(vm)

    def add_vpmu(self, id: Optional[int]=None):
        if id is None:
            id = next(i for i in range(MAX_IDS) if i not in self.vpmus)
        self.vpmus.add(id)

    def add_pagetables(self, pt: PageTables):
        self.pagetables.append(pt)

    def add_cspace(self, csp: CSpace):
        self.cspaces.append(csp)

    def add_reply(self, id: Optional[int]=None):
        if id is None:
            id = next(i for i in range(MAX_IDS) if i not in self.replys)
        self.replys.add(id)

    def __repr__(self):
        return f"<ProtectionDomain {self.name} prio={self.priority} at {hex(id(self))}>"
