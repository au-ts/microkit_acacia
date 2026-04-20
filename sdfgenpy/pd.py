# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Set
from dataclasses import dataclass
from abc import ABC
import xml.etree.ElementTree as et
from .memory import MemoryRegion, Map
from .arch import SDFMemoryAllocator
from .irq import IRQ

@dataclass
class SchedulingProperties:
    """
    Properties of an entity for the seL4 scheduler
    """
    priority: int
    period: Optional[int] = None
    budget: Optional[int] = None
    passive: bool = False

    def __post_init__(self):
        # Enforce sane values
        if self.priority is None:
            raise ValueError("Must define a priority!")
        for field in [self.priority, self.budget, self.period]:
            if field is None:
                continue
            if not isinstance(field, int):
                raise ValueError(f"Int field given {type(field)} instead!")
            if field < 0:
                raise ValueError("SchedulingProperties cannot be negative!")

        # If we have a period, we must also have a budget
        if self.period is not None:
            if (budget > period):
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
        self.maps: List[Map] = []

    def add_map(self, map: Map):
        self.maps.append(map)

    def name(self):
        return self.name

    @property
    def priority(self):
        return self.scheduling.priority

    @property
    def budget(self):
        return self.scheduling.budget

    @property
    def period(self):
        return self.scheduling.period

    def render(self, parent: et.Element, elem_name: str):
        entity = et.SubElement(parent, elem_name)
        entity.set("name", str(self.name))
        entity.set("priority", str(self.scheduling.priority))
        # Only add passive bool if true
        if self.scheduling.passive:
            entity.set("passive", "true")
        # Invariant: SchedulingProperties dataclass prevents us from having
        # periods and budgets while also being passive
        if self.scheduling.period is not None:
            entity.set("period", str(self.scheduling.period))
        if self.scheduling.budget is not None:
            entity.set("budget", str(self.scheduling.budget))

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

        return pd

    def add_irq(self, irq: IRQ):
        if irq in self.irqs:
            raise RuntimeError("Cannot add the same IRQ to a PD twice!")
        self.irqs.add(irq)

class VMProtectionDomain(Entity):
    """
    """
    pass
