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
            return "edge" if self.value == self.EDGE.value else "level"

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
        irq.set("irq", str(self.irq_num))
        irq.set("id", str(self.id))
        irq.set("trigger", str(self.trigger))

    @property
    def number(self):
        return self.irq_num

    @property
    def trigger(self):
        return self._trigger


class IrqIoapic(IRQ):
    class Polarity(Enum):
        ACTIVEHIGH = 0
        ACTIVELOW = 1
        def __str__(self):
            return str(self.value)

    def __init__(self,
                 ioapic_id: int,
                 pin: int,
                 vector: int,
                 trigger: Optional[IRQ.Trigger] = None,
                 polarity: Optional[Polarity] = None,
                 id: Optional[int] = None):

        super().__init__(ioapic_id, id=id)
        self.pin = pin
        self.vector = vector
        self._trigger = trigger
        self.polarity = polarity

    # TODO: test this is correct
    def render(self, parent: et.Element):
        if self.id is None:
            raise RuntimeError("ID must be set before rendering an IRQ!")
        irq = et.SubElement(parent, "irq")
        irq.set("pin", str(self.pin))
        irq.set("vector", str(self.vector))
        irq.set("id", str(self.id))
        if self.irq is not None:
            irq.set("ioapic", str(self.irq))
        if self._trigger is not None:
            irq.set("trigger", self._trigger.name.lower())
        if self.polarity is not None:
            irq.set("polarity", self.polarity.name.lower())

    @property
    def number(self):
        raise RuntimeError("Number called on IOAPIC IRQ - invalid!")

    @property
    def trigger(self):
        return self._trigger


class IrqMsi(IRQ):
    def __init__(self,
                 pci_bus: int,
                 pci_device: int,
                 pci_func: int,
                 vector: int,
                 handle: int,
                 id: Optional[int] = None):

        super().__init__(handle, id=id)
        self.pci_bus = pci_bus
        self.pci_device = pci_device
        self.pci_func = pci_func
        self.vector = vector

    # TODO: test this is correct
    def render(self, parent: et.Element):
        if self.id is None:
            raise RuntimeError("ID must be set before rendering an IRQ!")
        irq = et.SubElement(parent, "irq")
        irq.set("pcidev", f"{self.pci_bus}:{self.pci_device}.{self.pci_func}")
        irq.set("handle", str(self.irq))
        irq.set("vector", str(self.vector))
        irq.set("id", str(self.id))

    @property
    def number(self):
        raise RuntimeError("Number called on MSI IRQ - invalid!")

    @property
    def trigger(self):
        raise RuntimeError("Trigger called on MSI IRQ - invalid!")


