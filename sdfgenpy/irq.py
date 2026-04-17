# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from abc import ABC, abstractproperty
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as et


class IRQ:
    @dataclass(frozen=True)
    class Trigger(Enum):
        EDGE = 0
        LEVEL = 1

    def __init__(self, id: int):
        self.id = id

    @property
    def id(self):
        return self.id

    @abstractproperty
    def trigger(self):
        pass

    @abstractproperty
    def render(self, parent: et.Element):
        pass

class ConventionalIRQ(IRQ):
    """
    IRQs on ARM and RISC-V machines.
    """
    def __init__(self, id: int, irq_num: int, trigger: IRQ.Trigger):
        super().__init__(self, id)
        self.irq_num = irq_num
        self.trigger = trigger

    @property
    def irq_num(self):
        return self.irq_num

    @property
    def trigger(self):
        return self.trigger

    def render(self, parent: et.Element):
        irq = et.SubElement(parent, "irq")
        irq.set("id", self.id)
        irq.set("trigger", self.trigger)
