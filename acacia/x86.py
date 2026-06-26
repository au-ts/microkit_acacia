# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from abc import ABC, abstractproperty, abstractmethod
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as et
from typing import Optional
from .irq import IRQ


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


class IOPort:
    """
    A representation of an x86 IOPort.
    """
    def __init__(self,
                 addr: int,
                 size: int,
                 id: Optional[int] = None):
        self.addr = addr
        self.size = size
        self.id = id


    def render(self, parent: et.Element):
        # ID should be set by PD when calling pd.add_ioport()
        if self.id is None:
            raise RuntimeError("ID must be set before rendering an ioport!")
        ioport = et.SubElement(parent, "ioport")
        ioport.set("id", str(self.id))
        ioport.set("addr", str(self.addr))
        ioport.set("size", str(self.size))

