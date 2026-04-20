# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from abc import ABC, abstractproperty, abstractmethod
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as et


class IRQ:
    @dataclass(frozen=True)
    class Trigger(Enum):
        EDGE = 0
        LEVEL = 1

        def __str__(self):
            return str(self.value)

    def __init__(self, id: int):
        self.id = id

    @abstractmethod
    def render(self, parent: et.Element):
        pass

class ConventionalIRQ(IRQ):
    """
    IRQs on ARM and RISC-V machines.
    """
    def __init__(self, id: int, irq_num: int, trigger: IRQ.Trigger):
        super().__init__(id)
        self.irq_num = irq_num
        self.trigger = trigger

    def render(self, parent: et.Element):
        irq = et.SubElement(parent, "irq")
        irq.set("id", str(self.id))
        irq.set("trigger", str(self.trigger))
