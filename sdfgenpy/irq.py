# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from abc import ABC, abstractproperty, abstractmethod
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as et
from typing import Optional

# Note: x86 IRQ types are in x86.py

class IRQ:
    class Trigger(Enum):
        EDGE = 0
        LEVEL = 1

        def __str__(self):
            return str(self.value)

    def __init__(self, irq: int, id: Optional[int] = None):
        self.id = id
        self.irq = irq

    @abstractproperty
    def number(self):
        pass

    @abstractproperty
    def trigger(self):
        pass

    @abstractmethod
    def render(self, parent: et.Element):
        pass


class ConventionalIRQ(IRQ):
    """
    IRQs on ARM and RISC-V machines.
    """
    def __init__(self, irq_num: int, trigger: IRQ.Trigger, id: Optional[int]=None):
        super().__init__(irq_num, id=id)
        self.irq_num = irq_num
        self._trigger = trigger

    def render(self, parent: et.Element):
        if self.id is None:
            raise RuntimeError("ID must be set before rendering an IRQ!")
        irq = et.SubElement(parent, "irq")
        irq.set("id", str(self.id))
        irq.set("trigger", str(self.trigger))

    @property
    def number(self):
        return self.irq

    @property
    def trigger(self):
        return self._trigger



