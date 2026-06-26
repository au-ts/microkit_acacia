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
        if self.priority is None:
            raise ValueError("Must define a priority!")
        for field in [self.priority, self.budget]:
            if field is None:
                continue
            if not isinstance(field, int):
                raise ValueError(f"Int field given {type(field)} instead!")
            if field < 0:
                raise ValueError("SchedulingProperties cannot be negative!")

        # If we have a period, we must also have a budget
        if self.period is not None:
            if self.budget and self.period and (self.budget > self.period):
                raise ValueError("Budget cannot be greater than period!")
        # Passive PDs may not have a period or budget
        if self.passive and (self.period is not None or self.budget is not None):
            raise ValueError("Passive PDs do not have a period or budget!")


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
        # self.priority = DependentField(0, 254).set_val(scheduling.priority)
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
                       start_vaddr=0x20_000_000) -> Map:
        """
        Given a memory region, automatically create a map and assign it a vaddr
        that doesn't overlap with any existing maps.

        Args:
            mr: MemoryRegion to map
            perms: Map permissions - read, write, execute
            start_vaddr: lowest address to auto-allocate map. Default: 0x20_000_000

        Returns:
            Map: created map object.

        NOTE: This replaces `getMapVaddr` in zig sdfgen.
        """
        if len(self.maps) != 0:
            print(self.maps)
            # python sorted() is adaptive, so this doesn't waste much time on repeats!
            self.maps = sorted(self.maps, key=lambda m: m.vaddr)
            last_vaddr_end = self.maps[-1].vaddr + self.maps[-1].size

            # pad by one page.
            # TODO: support doing this with the architecture page size. Currently,
            # we don't support any page sizes other than 0x1000 in general throughout
            # this codebase.
            next_vaddr = (last_vaddr_end - (last_vaddr_end % 0x1000)) + 0x1000
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
        # Invariant: SchedulingProperties dataclass prevents us from having
        # periods and budgets while also being passive
        if self.period is not None:
            entity.set("period", str(self.period))
        if self.budget is not None:
            entity.set("budget", str(self.budget))

        for map in self.maps:
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
            # todo: validate cpu field. Not entirely clear what this should be?

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
        if self.stack_size is not None:
            pd.set("stack_size", str(self.stack_size))
        if self.cpu is not None:
            pd.set("cpu", str(self.cpu))
        for i in self.irqs:
            i.render(pd)
        for iop in self.ioports:
            iop.render(pd)
        for c in self.children:
            c.render(pd)
        if self.vm:
            self.vm.render(pd)

        return pd

    # NOTE: Doing this incrementally is fragile. Especially with dependency resolution, we should
    # maybe refactor channel/irq ID allocation to happen all at once when rendering, or maybe at am
    # "implement" step.
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




