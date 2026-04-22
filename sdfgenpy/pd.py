# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Set, Union
from dataclasses import dataclass
from abc import ABC
import xml.etree.ElementTree as et
from .memory import MemoryRegion, Map
from .arch import SDFMemoryAllocator
from .irq import IRQ
from .x86 import IOPort
# from .constraint import DependentField, FieldSpec, UINT64_MAX

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
            if (self.budget > self.period):
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
        self.priority = scheduling.priority
        self.budget = scheduling.budget
        self.period = scheduling.period
        self.maps: List[Map] = []

    def add_map(self, map: Map):
        self.maps.append(map)

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

    def render(self, system_root: et.Element):
        pd = super().render(system_root, "protection_domain")
        prog_image = et.SubElement(pd, "program_image")
        prog_image.set("path", self.prog_image)

        # Only insert stack size, CPU and SMC if defined
        if self.stack_size is not None:
            pd.set("stack_size", str(self.stack_size))
        if self.cpu is not None:
            pd.set("cpu", str(self.cpu))
        for i in self.irqs:
            i.render(pd)
        for iop in self.ioports:
            iop.render(pd)

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
            new_id = next(i for i in range(254) if i not in self.assigned_ids)
            self.assigned_ids.append(new_id)
            return new_id


    def add_irq(self, irq: IRQ):
        if irq in self.irqs:
            raise RuntimeError("Cannot add the same IRQ to a PD twice!")

        irq.id = self.allocate_id(irq.id)   # Allocate and reserve ID
        self.irqs.add(irq)

    def add_ioport(self, ioport: IOPort):
        ioport.id = self.allocate_id(ioport.id)   # Allocate and reserve ID
        self.ioports.append(ioport)


class VMProtectionDomain(Entity):
    """
    """
    pass
