# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from acacia.irq import ConventionalIRQ, IRQ


class TestConventionalIRQ:
    def test_initialization(self):
        irq = ConventionalIRQ(42, IRQ.Trigger.EDGE, id=5)
        assert irq.irq_num == 42
        assert irq.irq == 42  # Stored in parent irq field
        assert irq.trigger == IRQ.Trigger.EDGE
        assert irq.id == 5

    def test_number_property(self):
        irq = ConventionalIRQ(42, IRQ.Trigger.EDGE, id=None)
        assert irq.number == 42

    def test_render_without_id_raises(self):
        irq = ConventionalIRQ(42, IRQ.Trigger.EDGE, id=None)
        with pytest.raises(RuntimeError, match="ID must be set"):
            irq.render(et.Element("parent"))

    def test_render_edge_trigger(self):
        irq = ConventionalIRQ(42, IRQ.Trigger.EDGE, id=1)
        parent = et.Element("parent")
        irq.render(parent)
        irq_elem = parent.find("irq")
        assert irq_elem.get("id") == "1"
        assert irq_elem.get("trigger") == "edge"

    def test_render_level_trigger(self):
        irq = ConventionalIRQ(42, IRQ.Trigger.LEVEL, id=2)
        parent = et.Element("parent")
        irq.render(parent)
        irq_elem = parent.find("irq")
        assert irq_elem.get("trigger") == "level"


class TestIRQTriggerEnum:
    def test_edge_value(self):
        assert IRQ.Trigger.EDGE.value == 0

    def test_level_value(self):
        assert IRQ.Trigger.LEVEL.value == 1

    def test_str_representation(self):
        assert str(IRQ.Trigger.EDGE) == "edge"
        assert str(IRQ.Trigger.LEVEL) == "level"

