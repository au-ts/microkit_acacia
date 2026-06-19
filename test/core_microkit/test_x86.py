# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from acacia.x86 import IrqIoapic, IrqMsi, IOPort


class TestIrqIoapic:
    def test_initialization(self):
        irq = IrqIoapic(
            ioapic_id=0,
            pin=4,
            vector=32,
            trigger=IrqIoapic.Trigger.EDGE,
            polarity=IrqIoapic.Polarity.ACTIVEHIGH
        )
        assert irq.pin == 4
        assert irq.vector == 32
        assert irq.irq == 0  # ioapic_id stored in irq field
        assert irq.trigger == IrqIoapic.Trigger.EDGE

    def test_number_raises(self):
        irq = IrqIoapic(0, 4, 32)
        with pytest.raises(RuntimeError, match="IOAPIC IRQ"):
            _ = irq.number

    def test_render_without_id_raises(self):
        irq = IrqIoapic(0, 4, 32)
        with pytest.raises(RuntimeError, match="ID must be set"):
            irq.render(et.Element("parent"))

    def test_render_basic(self):
        irq = IrqIoapic(0, 4, 32)
        irq.id = 1
        parent = et.Element("parent")
        irq.render(parent)
        irq_elem = parent.find("irq")
        assert irq_elem.get("pin") == "4"
        assert irq_elem.get("vector") == "32"
        assert irq_elem.get("id") == "1"
        assert irq_elem.get("ioapic") == "0"

    def test_render_with_trigger(self):
        irq = IrqIoapic(0, 4, 32, trigger=IrqIoapic.Trigger.LEVEL)
        irq.id = 1
        parent = et.Element("parent")
        irq.render(parent)
        irq_elem = parent.find("irq")
        assert irq_elem.get("trigger") == "level"

    def test_polarity_values(self):
        assert str(IrqIoapic.Polarity.ACTIVEHIGH) == "0"
        assert str(IrqIoapic.Polarity.ACTIVELOW) == "1"


class TestIrqMsi:
    def test_initialization(self):
        irq = IrqMsi(
            pci_bus=0,
            pci_device=3,
            pci_func=0,
            vector=64,
            handle=0
        )
        assert irq.pci_bus == 0
        assert irq.pci_device == 3
        assert irq.vector == 64
        assert irq.irq == 0  # handle stored in irq field

    def test_number_raises(self):
        irq = IrqMsi(0, 3, 0, 64, 0)
        with pytest.raises(RuntimeError, match="MSI IRQ"):
            _ = irq.number

    def test_trigger_raises(self):
        irq = IrqMsi(0, 3, 0, 64, 0)
        with pytest.raises(RuntimeError, match="MSI IRQ"):
            _ = irq.trigger

    def test_render_without_id_raises(self):
        irq = IrqMsi(0, 3, 0, 64, 0)
        with pytest.raises(RuntimeError, match="ID must be set"):
            irq.render(et.Element("parent"))

    def test_render(self):
        irq = IrqMsi(0, 3, 0, 64, 0)
        irq.id = 2
        parent = et.Element("parent")
        irq.render(parent)
        irq_elem = parent.find("irq")
        assert irq_elem.get("pcidev") == "0:3.0"
        assert irq_elem.get("vector") == "64"
        assert irq_elem.get("handle") == "0"
        assert irq_elem.get("id") == "2"


class TestIOPort:
    def test_initialization(self):
        ioport = IOPort(addr=0x3f8, size=0x8)
        assert ioport.addr == 0x3f8
        assert ioport.size == 0x8

    def test_render_without_id_raises(self):
        ioport = IOPort(0x3f8, 0x8)
        with pytest.raises(RuntimeError, match="ID must be set"):
            ioport.render(et.Element("parent"))

    def test_render(self):
        ioport = IOPort(0x3f8, 0x8)
        ioport.id = 3
        parent = et.Element("parent")
        ioport.render(parent)
        iop_elem = parent.find("ioport")
        assert iop_elem.get("id") == "3"
        assert iop_elem.get("addr") == "0x3f8"
        assert iop_elem.get("size") == "0x8"

