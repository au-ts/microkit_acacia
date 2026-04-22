# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from sdfgenpy.pd import ProtectionDomain, SchedulingProperties, VMProtectionDomain
from sdfgenpy.memory import MemoryRegion, Map


class TestSchedulingProperties:
    def test_priority_required(self):
        with pytest.raises(ValueError, match="Must define a priority"):
            SchedulingProperties(priority=None)

    def test_negative_priority_rejected(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            SchedulingProperties(priority=-1)

    def test_negative_budget_rejected(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            SchedulingProperties(priority=100, budget=-10, period=100)

    def test_budget_exceeds_period_rejected(self):
        with pytest.raises(ValueError, match="Budget cannot be greater than period"):
            SchedulingProperties(priority=100, budget=200, period=100)

    def test_passive_with_period_rejected(self):
        with pytest.raises(ValueError, match="Passive PDs do not have a period"):
            SchedulingProperties(priority=100, passive=True, period=100)

    def test_passive_with_budget_rejected(self):
        with pytest.raises(ValueError, match="Passive PDs do not have a period"):
            SchedulingProperties(priority=100, passive=True, budget=100)

    def test_valid_scheduling(self):
        sp = SchedulingProperties(priority=100, budget=50, period=100)
        assert sp.priority == 100
        assert sp.budget == 50
        assert sp.period == 100
        assert not sp.passive

    def test_valid_passive(self):
        sp = SchedulingProperties(priority=100, passive=True)
        assert sp.passive
        assert sp.period is None
        assert sp.budget is None


class TestProtectionDomain:
    def test_invalid_program_image(self):
        with pytest.raises(ValueError, match="Non-elf"):
            ProtectionDomain("test", "test.bin")

    def test_valid_program_image(self):
        pd = ProtectionDomain("test", "test.elf")
        assert pd.prog_image == "test.elf"

    def test_priority_convenience_constructor(self):
        pd = ProtectionDomain("test", "test.elf", priority=100)
        assert pd.priority == 100

    def test_priority_and_scheduling_conflict(self):
        sp = SchedulingProperties(priority=100)
        with pytest.raises(RuntimeError, match="Cannot define.*SchedulingCharacteristics"):
            ProtectionDomain("test", "test.elf", priority=50, scheduling=sp)

    def test_stack_size_cpu_optional(self):
        pd = ProtectionDomain("test", "test.elf", priority=100)
        pd.render(et.Element("system"))
        # Should not raise even without stack_size or cpu

    def test_stack_size_rendered(self):
        pd = ProtectionDomain("test", "test.elf", priority=100, stack_size=0x1000)
        root = et.Element("system")
        pd.render(root)
        pd_elem = root.find("protection_domain")
        assert pd_elem.get("stack_size") == "4096"

    def test_cpu_rendered(self):
        pd = ProtectionDomain("test", "test.elf", priority=100, cpu=2)
        root = et.Element("system")
        pd.render(root)
        pd_elem = root.find("protection_domain")
        assert pd_elem.get("cpu") == "2"

    def test_add_map(self):
        pd = ProtectionDomain("test", "test.elf", priority=100)
        mr = MemoryRegion("test_mr", 0x1000)
        m = Map(mr, 0x40000000, "rw")
        pd.add_map(m)
        assert len(pd.maps) == 1


class TestProtectionDomainIdAllocation:
    def test_allocate_id_auto(self):
        pd = ProtectionDomain("test", "test.elf", priority=100)
        id1 = pd.allocate_id()
        id2 = pd.allocate_id()
        assert id1 != id2
        assert id1 in pd.assigned_ids
        assert id2 in pd.assigned_ids

    def test_allocate_id_specific(self):
        pd = ProtectionDomain("test", "test.elf", priority=100)
        id_val = pd.allocate_id(requested_id=5)
        assert id_val == 5

    def test_allocate_id_duplicate_rejected(self):
        pd = ProtectionDomain("test", "test.elf", priority=100)
        pd.allocate_id(requested_id=5)
        with pytest.raises(RuntimeError, match="not available"):
            pd.allocate_id(requested_id=5)

    def test_allocate_id_reserves_range(self):
        pd = ProtectionDomain("test", "test.elf", priority=100)
        # Fill first few slots
        for i in range(5):
            pd.allocate_id()
        # Request specific higher ID should work
        id_val = pd.allocate_id(requested_id=10)
        assert id_val == 10

    def test_allocate_id_limit(self):
        pd = ProtectionDomain("test", "test.elf", priority=100)
        # Fill all slpts
        for i in range(254):
            pd.allocate_id()
        # Should fail to allocate any more
        with pytest.raises(StopIteration):
            id_val = pd.allocate_id()


class TestProtectionDomainIrq:
    def test_add_irq_allocates_id(self):
        from sdfgenpy.irq import ConventionalIRQ
        pd = ProtectionDomain("test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=None)
        pd.add_irq(irq)
        assert irq.id is not None
        assert irq.id in pd.assigned_ids

    def test_add_irq_specific_id(self):
        from sdfgenpy.irq import ConventionalIRQ
        pd = ProtectionDomain("test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=7)
        pd.add_irq(irq)
        assert irq.id == 7

    def test_add_same_irq_twice_rejected(self):
        from sdfgenpy.irq import ConventionalIRQ
        pd = ProtectionDomain("test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=None)
        pd.add_irq(irq)
        with pytest.raises(RuntimeError, match="same IRQ"):
            pd.add_irq(irq)


# class TestVMProtectionDomain:
