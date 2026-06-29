# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Set, Union, List
from dataclasses import dataclass
from abc import ABC
import xml.etree.ElementTree as et
from .memory import MemoryRegion, Map
from .arch import SDFMemoryAllocator
from .irq import IRQ
from .x86 import IOPort
# from .constraint import DependentField, FieldSpec, UINT64_MAX

MAX_IDS = 62 # matches microkit. limit for child pds, ioports, irqs and channel IDs

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
        for field in [self.period, self.budget]:
            if field is None:
                continue
            if not isinstance(field, int):
                raise ValueError(f"SchedulingProperties int field given {type(field)} instead!")
            if field < 0:
                raise ValueError("SchedulingProperties cannot be negative!")

        # If we have a period, we must also have a budget, and the b
        if self.period is not None:
            if self.budget is None or self.budget > self.period:
                raise ValueError("Budget must be defined and cannot be greater than period!")


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
            scheduling: SchedulingProperties
    ):
        self.name = name.strip()
        self.scheduling = scheduling
        self.maps: List[Map] = []

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

    def create_automap(self, mr: MemoryRegion, perms: Union[Map.Permissions, str],
                       start_vaddr=0x20_000_000, page_size=0x1000) -> Map:
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
            last_vaddr_end = self.maps[-1].vaddr + self.maps[-1].size

            # pad by one page
            if last_vaddr_end % page_size:
                next_vaddr = (last_vaddr_end - (last_vaddr_end % page_size)) + page_size 
            else:
                next_vaddr = last_vaddr_end

            # Add space for a guard page
            next_vaddr += page_size
        else:
            next_vaddr = start_vaddr

        m = Map(mr, next_vaddr, perms)
        self.add_map(m)
        return m

    def name(self):
        return self.name

    def render(self, parent: et.Element, elem_name: str):
        entity = et.SubElement(parent, elem_name)
        entity.set("name", str(self.name))
        if self.priority is None:
            raise RuntimeError("Cannot render an entity without a priority!")

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

    def __init__(self,
                 name: str,
                 scheduling: SchedulingProperties,
                 vcpus: [Union[List[VCPU], VCPU]]):
        super().__init__(name, scheduling)
        if type(vcpus) is not list:
            self.vcpus = [vcpus]
        else:
            # Check all IDs are unique
            ids = [x.id for x in vcpus]
            if len(ids) != len(set(ids)):
                raise RuntimeError("All VCPU IDs must be unique per VM!")
            if len(ids) > MAX_IDS:
                raise RuntimeError(f"{MAX_IDS} VCPUs are supported at max!")
            self.vcpus = vcpus

    def render(self, parent: et.Element):
        vm = super().render(parent, "virtual_machine")
        for vcpu in self.vcpus:
            vcpu.render(vm)


class ProtectionDomain(Entity):
    """
    A PD running native code
    """
    def __init__(
            self,
            name: str,
            prog_image: str,
            stack_size: Optional[int] = None,
            cpu: Optional[int] = None,
            smc: Optional[bool] = None,
            scheduling: SchedulingProperties = None,
            priority: Optional[int] = None):

        # We offer `priority=x` as a legacy feature
        if priority is not None:
            if scheduling is not None:
                raise RuntimeError("Cannot define a SchedulingCharacteristics and priority separately!")
            scheduling = SchedulingProperties(priority)
        super().__init__(name, scheduling)
        if not prog_image.endswith(".elf"):
            raise ValueError("Non-elf program image!")
        self.prog_image = prog_image
        self.stack_size = stack_size
        self.cpu = cpu
        self.irqs: Set[IRQ] = set()
        self.ioports: List[IOPort] = []
        self.assigned_ids = []

        # Parental responsibilities
        self.assigned_child_ids = []
        self.children: List[ProtectionDomain] = []
        self.child_id = None    # Assigned if this PD is made a child.

        # VM
        self.vm: Optional[VirtualMachine] = None

    def render(self, parent: et.Element):
        pd = super().render(parent, "protection_domain")
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
        for i in sorted(self.irqs, key=lambda ir: ir.id):
            i.render(pd)
        for iop in sorted(self.ioports, key=lambda i: i.addr):
            iop.render(pd)
        for c in sorted(self.children, key=lambda c: c.name):
            c.render(pd)
        if self.vm:
            self.vm.render(pd)

        return pd

    def allocate_id(self, requested_id: Optional[int] = None):
        """
        Allocate an ID (or test a requested id) for a channel or IRQ.
        """
        if requested_id is not None:
            if requested_id not in self.assigned_ids:
                self.assigned_ids.append(requested_id)
                return requested_id
            else:
                raise RuntimeError("Requested ID is not available!")

        else:
            new_id = next(i for i in range(MAX_IDS) if i not in self.assigned_ids)
            self.assigned_ids.append(new_id)
            return new_id

    def allocate_child_pd_id(self, requested_id: Optional[int] = None):
        """
        Allocate an ID (or test a requested id) for a child PD
        """
        if requested_id is not None:
            if requested_id not in self.assigned_child_ids:
                self.assigned_child_ids.append(requested_id)
                return requested_id
            else:
                raise RuntimeError("Requested ID is not available!")

        else:
            new_id = next(i for i in range(MAX_IDS) if i not in self.assigned_child_ids)
            self.assigned_child_ids.append(new_id)
            return new_id

    def add_irq(self, irq: IRQ):
        if irq in self.irqs:
            raise RuntimeError("Cannot add the same IRQ to a PD twice!")

        irq.id = self.allocate_id(irq.id)   # Allocate and reserve ID
        self.irqs.add(irq)
        return irq.id

    def add_ioport(self, ioport: IOPort):
        ioport.id = self.allocate_id(ioport.id)   # Allocate and reserve ID
        self.ioports.append(ioport)

    def add_child_pd(self, child, child_id: Optional[int] = None):
        if child in self.children:
            raise RuntimeError("Cannot make the same PD a child multiple times!")
        child_id = self.allocate_child_pd_id(child_id)
        child.child_id = child_id
        self.children.append(child)

    def set_vm(self, vm: VirtualMachine):
        if self.vm is not None:
            raise RuntimeError("Can only have one VM per PD!")
        self.vm = vm

    def __repr__(self):
        return f"<ProtectionDomain {self.name} prio={self.priority} at {hex(id(self))}>"
