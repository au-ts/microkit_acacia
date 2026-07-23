# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from unittest.mock import MagicMock, patch
from acacia.pd import ProtectionDomain, SchedulingProperties, MAX_IDS, VirtualMachine
from acacia.memory import MemoryRegion, Map
from acacia.channel import Channel
from acacia.irq import ConventionalIRQ
from acacia.system import System
from acacia.arch import aarch64, x86_64


@pytest.fixture
def sdf():
    """A stand-in System for entity constructors."""
    return System(aarch64, paddr_top=0x10000000)


@pytest.fixture
def x86sdf():
    """Stand-in system for checking x86-specific behaviour"""
    return System(x86_64, paddr_top=0x10000000)


@pytest.fixture
def arch():
    """A stand-in Arch with a deterministic page size."""
    a = MagicMock(name="arch")
    a.default_page_size.return_value = 0x1000
    return a


class TestSchedulingProperties:
    def test_priority_required(self):
        with pytest.raises(ValueError, match="Must define a non-negative priority"):
            SchedulingProperties(priority=None)

    def test_negative_priority_rejected(self):
        with pytest.raises(ValueError, match="Must define a non-negative priority"):
            SchedulingProperties(priority=-1)

    def test_budget_exceeds_period_rejected(self):
        with pytest.raises(
            ValueError, match="Budget must be defined and cannot be greater than period"
        ):
            SchedulingProperties(priority=100, budget=200, period=100)

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
    def test_invalid_program_image(self, sdf):
        with pytest.raises(ValueError, match="Non-elf"):
            ProtectionDomain(sdf, "test", "test.bin")

    def test_valid_program_image(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf")
        assert pd.prog_image == "test.elf"

    def test_priority_convenience_constructor(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        assert pd.priority == 100

    def test_priority_and_scheduling_conflict(self, sdf):
        sp = SchedulingProperties(priority=100)
        with pytest.raises(
            RuntimeError, match="Cannot define.*SchedulingCharacteristics"
        ):
            ProtectionDomain(sdf, "test", "test.elf", priority=50, scheduling=sp)

    def test_stack_size_cpu_optional(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        pd.render(et.Element("system"))
        # Should not raise even without stack_size or cpu

    def test_stack_size_rendered(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100, stack_size=0x1000)
        root = et.Element("system")
        pd.render(root)
        pd_elem = root.find("protection_domain")
        assert pd_elem.get("stack_size") == "4096"

    def test_cpu_rendered(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100, cpu=2)
        root = et.Element("system")
        pd.render(root)
        pd_elem = root.find("protection_domain")
        assert pd_elem.get("cpu") == "2"

    def test_add_map(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        m = Map(mr, 0x40000000, "rw")
        pd.add_map(m)
        assert len(pd.maps) == 1


class TestProtectionDomainIdAllocation:
    def test_allocate_id_auto(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        id1 = pd.allocate_id()
        id2 = pd.allocate_id()
        # nothing should happen, we didn't assign those IDs to anything!
        assert id1 == 0
        assert id2 == 0

    def test_allocate_id_specific(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        id_val = pd.allocate_id(requested_id=5)
        assert id_val == 5

    def test_allocate_id_duplicate_irq_rejected(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=5)
        pd.add_irq(irq)
        with pytest.raises(RuntimeError, match="not available"):
            pd.allocate_id(requested_id=5)

    def test_allocate_id_duplicate_channel_rejected(self, sdf):
        pd1 = ProtectionDomain(sdf, "pd1", "pd1.elf", priority=100)
        pd2 = ProtectionDomain(sdf, "pd2", "pd2.elf", priority=200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=False, ch_id=5)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=6)
        Channel(sdf, end_a, end_b)

        with pytest.raises(RuntimeError, match="not available"):
            pd1.allocate_id(requested_id=5)
        with pytest.raises(RuntimeError, match="not available"):
            pd2.allocate_id(requested_id=6)

    def test_allocate_id_reserves_range(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        # Occupy the first five IDs with IRQs.
        for i in range(5):
            irq = ConventionalIRQ(i, ConventionalIRQ.Trigger.EDGE, id=i)
            pd.add_irq(irq)

        id_val = pd.allocate_id(requested_id=10)
        assert id_val == 10

    def test_allocate_id_limit(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        # Fill all slots with IRQs.
        for i in range(MAX_IDS):
            irq = ConventionalIRQ(i, ConventionalIRQ.Trigger.EDGE, id=i)
            pd.add_irq(irq)

        with pytest.raises(StopIteration):
            pd.allocate_id()

    def test_allocate_id_respects_channel_ids_in_same_system(self, sdf):
        pd1 = ProtectionDomain(sdf, "pd1", "pd1.elf", priority=100)
        pd2 = ProtectionDomain(sdf, "pd2", "pd2.elf", priority=200)
        # Create a channel whose ends occupy IDs 0 and 1.
        Channel(
            sdf,
            Channel.End(pd1, can_notify=True, can_pp=False, ch_id=0),
            Channel.End(pd2, can_notify=True, can_pp=False, ch_id=1),
        )
        assert pd1.allocate_id() == 1
        assert pd2.allocate_id() == 0


class TestProtectionDomainIrq:
    def test_add_irq_allocates_id(self, sdf):
        from acacia.irq import ConventionalIRQ

        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=None)
        pd.add_irq(irq)
        assert irq.id is not None

    def test_add_irq_specific_id(self, sdf):
        from acacia.irq import ConventionalIRQ

        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=7)
        pd.add_irq(irq)
        assert irq.id == 7

    def test_add_same_irq_twice_rejected(self, sdf):
        from acacia.irq import ConventionalIRQ

        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=None)
        pd.add_irq(irq)
        with pytest.raises(RuntimeError, match="same IRQ"):
            pd.add_irq(irq)


class TestChildPdAddition:
    def test_add_child_auto_id(self, sdf):
        parent = ProtectionDomain(sdf, "parent", "parent.elf", priority=100)
        child = ProtectionDomain(sdf, "child", "child.elf", priority=50)
        parent.add_child_pd(child)
        assert child.child_id is not None
        assert child in parent.children

    def test_add_child_specific_id(self, sdf):
        parent = ProtectionDomain(sdf, "parent", "parent.elf", priority=100)
        child = ProtectionDomain(sdf, "child", "child.elf", priority=50)
        parent.add_child_pd(child, child_id=10)
        assert child.child_id == 10

    def test_add_same_child_twice_rejected(self, sdf):
        parent = ProtectionDomain(sdf, "parent", "parent.elf", priority=100)
        child = ProtectionDomain(sdf, "child", "child.elf", priority=50)
        parent.add_child_pd(child)
        with pytest.raises(RuntimeError, match="same PD"):
            parent.add_child_pd(child)

    def test_add_child_max_ids_exhausted(self, sdf):
        parent = ProtectionDomain(sdf, "parent", "parent.elf", priority=100)
        # Fill up all child slots
        for i in range(MAX_IDS):
            child = ProtectionDomain(sdf, f"child_{i}", f"child_{i}.elf", priority=50)
            parent.add_child_pd(child)

        # Next one should fail when trying to find next available
        extra_child = ProtectionDomain(sdf, "extra", "extra.elf", priority=50)
        with pytest.raises(StopIteration):  # next() fails when all ids used
            parent.add_child_pd(extra_child)


class TestChildPdRendering:
    def test_child_rendered_as_nested_element(self, sdf):
        parent = ProtectionDomain(sdf, "parent", "parent.elf", priority=100)
        child = ProtectionDomain(sdf, "child", "child.elf", priority=50)
        parent.add_child_pd(child, child_id=2)

        root = et.Element("system")
        parent.render(root)

        parent_elem = root.find("protection_domain")
        assert parent_elem.get("name") == "parent"

        child_elem = parent_elem.find("protection_domain")
        assert child_elem is not None
        assert child_elem.get("name") == "child"
        assert child_elem.get("id") == "2"

    def test_child_without_parent_no_id_attribute(self, sdf):
        child = ProtectionDomain(sdf, "child", "child.elf", priority=50)
        root = et.Element("system")
        child.render(root)

        child_elem = root.find("protection_domain")
        assert child_elem.get("id") is None

    def test_multiple_children_rendered(self, sdf):
        parent = ProtectionDomain(sdf, "parent", "parent.elf", priority=100)
        child1 = ProtectionDomain(sdf, "child1", "child1.elf", priority=50)
        child2 = ProtectionDomain(sdf, "child2", "child2.elf", priority=50)

        parent.add_child_pd(child1, child_id=1)
        parent.add_child_pd(child2, child_id=2)

        root = et.Element("system")
        parent.render(root)

        parent_elem = root.find("protection_domain")
        children = parent_elem.findall("protection_domain")
        assert len(children) == 2
        ids = [c.get("id") for c in children]
        assert "1" in ids
        assert "2" in ids

    def test_nested_grandchildren(self, sdf):
        grandparent = ProtectionDomain(sdf, "gp", "gp.elf", priority=200)
        parent = ProtectionDomain(sdf, "parent", "parent.elf", priority=100)
        child = ProtectionDomain(sdf, "child", "child.elf", priority=50)

        grandparent.add_child_pd(parent, child_id=1)
        parent.add_child_pd(
            child, child_id=1
        )  # Different namespace, same number allowed

        root = et.Element("system")
        grandparent.render(root)

        gp_elem = root.find("protection_domain")
        parent_elem = gp_elem.find("protection_domain")
        child_elem = parent_elem.find("protection_domain")

        assert gp_elem.get("id") is None  # Top level
        assert parent_elem.get("id") == "1"
        assert child_elem.get("id") == "1"


class TestChildPdIntegration:
    def test_child_with_maps_and_irqs(self, sdf):
        from acacia.irq import ConventionalIRQ

        parent = ProtectionDomain(sdf, "parent", "parent.elf", priority=100)
        child = ProtectionDomain(sdf, "child", "child.elf", priority=50)
        parent.add_child_pd(child, child_id=3)

        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        child.add_map(Map(mr, 0x40000000, "rw"))

        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=None)
        child.add_irq(irq)

        root = et.Element("system")
        parent.render(root)

        child_elem = root.find("protection_domain").find("protection_domain")

        # Check map rendered
        map_elem = child_elem.find("map")
        assert map_elem.get("vaddr") == "0x40000000"

        # Check IRQ rendered with allocated ID
        irq_elem = child_elem.find("irq")
        assert irq_elem is not None
        assert irq_elem.get("id") is not None


class TestVCPU:
    def test_valid_vcpu(self):
        v = VirtualMachine.VCPU(id=5, cpu=2)
        assert v.id == 5
        assert v.cpu == 2

    def test_vcpu_optional_cpu(self):
        v = VirtualMachine.VCPU(id=3)
        assert v.cpu is None

    def test_vcpu_negative_id_rejected(self):
        with pytest.raises(RuntimeError, match="VCPU ID.*is invalid"):
            VirtualMachine.VCPU(id=-1)

    def test_vcpu_id_exceeds_max(self):
        with pytest.raises(RuntimeError, match="VCPU ID.*is invalid"):
            VirtualMachine.VCPU(id=63)  # MAX_IDS is 62

    def test_vcpu_render(self):
        v = VirtualMachine.VCPU(id=4, cpu=1)
        parent = et.Element("parent")
        v.render(parent)
        vcpu_elem = parent.find("vcpu")
        assert vcpu_elem.get("id") == "4"
        assert vcpu_elem.get("cpu") == "1"

    def test_vcpu_render_no_cpu(self):
        v = VirtualMachine.VCPU(id=2)
        parent = et.Element("parent")
        v.render(parent)
        vcpu_elem = parent.find("vcpu")
        assert vcpu_elem.get("cpu") is None


class TestVirtualMachine:
    def test_init_with_single_vcpu(self):
        v = VirtualMachine.VCPU(id=0)
        vm = VirtualMachine(
            "vm1", vcpus=[v], scheduling=SchedulingProperties(priority=100)
        )
        assert isinstance(vm.vcpus, list)
        assert len(vm.vcpus) == 1

    def test_init_with_vcpu_list(self):
        vcpus = [VirtualMachine.VCPU(id=0), VirtualMachine.VCPU(id=1)]
        vm = VirtualMachine(
            "vm2", vcpus=vcpus, scheduling=SchedulingProperties(priority=100)
        )
        assert len(vm.vcpus) == 2

    def test_duplicate_vcpu_ids_rejected(self):
        vcpus = [VirtualMachine.VCPU(id=0), VirtualMachine.VCPU(id=0)]
        with pytest.raises(RuntimeError, match="unique per VM"):
            VirtualMachine(
                "vm3", vcpus=vcpus, scheduling=SchedulingProperties(priority=100)
            )

    def test_too_many_vcpus_rejected(self):
        vcpus = [VirtualMachine.VCPU(id=i) for i in range(63)]  # MAX_IDS is 62
        with pytest.raises(RuntimeError, match="supported at max"):
            VirtualMachine(
                "vm4", vcpus=vcpus, scheduling=SchedulingProperties(priority=100)
            )

    def test_vm_inherits_entity_maps(self, sdf):
        vm = VirtualMachine(
            "vm5",
            vcpus=[VirtualMachine.VCPU(id=0)],
            scheduling=SchedulingProperties(priority=100),
        )
        mr = MemoryRegion(sdf, "test_mr", 0x1000)
        m = Map(mr, 0x40000000, "rw")
        vm.add_map(m)
        assert len(vm.maps) == 1

    def test_vm_render_structure(self):
        vm = VirtualMachine(
            "guest",
            vcpus=[VirtualMachine.VCPU(id=0), VirtualMachine.VCPU(id=1)],
            scheduling=SchedulingProperties(priority=50, budget=1000, period=2000),
        )
        parent = et.Element("parent")
        vm.render(parent)
        vm_elem = parent.find("virtual_machine")
        assert vm_elem is not None
        assert vm_elem.get("name") == "guest"
        assert vm_elem.get("priority") == "50"
        assert vm_elem.get("budget") == "1000"
        assert vm_elem.get("period") == "2000"
        # Check VirtualMachine.VCPUs rendered inside
        vcpus = vm_elem.findall("vcpu")
        assert len(vcpus) == 2


class TestProtectionDomainVM:
    def test_add_vm_success(self, sdf):
        pd = ProtectionDomain(sdf, "vmm", "vmm.elf", priority=254)
        vm = VirtualMachine(
            "guest",
            vcpus=[VirtualMachine.VCPU(id=0)],
            scheduling=SchedulingProperties(priority=100),
        )
        pd.add_vm(vm)
        assert vm in pd.vms

    def test_x86_add_vm_scheduling_rejected(self, x86sdf):
        pd = ProtectionDomain(x86sdf, "vmm", "vmm.elf", priority=254)
        vm1 = VirtualMachine(
            "guest1",
            vcpus=[VirtualMachine.VCPU(id=0)],
            scheduling=SchedulingProperties(priority=100),
        )
        with pytest.raises(
            ValueError, match="VMs do not support scheduling properties on x86"
        ):
            pd.add_vm(vm1)

    def test_x86_add_vm_twice_rejected(self, x86sdf):
        pd = ProtectionDomain(x86sdf, "vmm", "vmm.elf", priority=254)
        vm1 = VirtualMachine(
            "guest1",
            vcpus=[VirtualMachine.VCPU(id=0)],
        )
        vm2 = VirtualMachine(
            "guest2",
            vcpus=[VirtualMachine.VCPU(id=1)],
        )
        pd.add_vm(vm1)
        with pytest.raises(ValueError, match="x86 systems do not support"):
            pd.add_vm(vm2)

    def test_vm_rendered_inside_pd(self, sdf):
        pd = ProtectionDomain(sdf, "vmm", "vmm.elf", priority=254)
        vm = VirtualMachine(
            "guest",
            vcpus=[VirtualMachine.VCPU(id=0)],
            scheduling=SchedulingProperties(priority=100),
        )
        pd.add_vm(vm)
        root = et.Element("system")
        pd.render(root)
        pd_elem = root.find("protection_domain")
        vm_elem = pd_elem.find("virtual_machine")
        assert vm_elem is not None
        assert vm_elem.get("name") == "guest"

    def test_vm_with_maps_rendered(self, sdf):
        pd = ProtectionDomain(sdf, "vmm", "vmm.elf", priority=254)
        mr = MemoryRegion(sdf, "ram", 0x1000)
        vm = VirtualMachine(
            "guest",
            vcpus=[VirtualMachine.VCPU(id=0)],
            scheduling=SchedulingProperties(priority=100),
        )
        vm.add_map(Map(mr, 0x40000000, "rw"))
        pd.add_vm(vm)
        root = et.Element("system")
        pd.render(root)
        vm_elem = root.find("protection_domain").find("virtual_machine")
        map_elem = vm_elem.find("map")
        assert map_elem is not None
        assert map_elem.get("vaddr") == "0x40000000"


class TestCreateAutomap:
    def test_first_map_uses_start_vaddr(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        mr = MemoryRegion(sdf, "mr", 0x1000)
        m = pd.create_automap(mr, "rw")
        assert m.vaddr == pd.map_start_vaddr
        assert m.vaddr % 0x1000 == 0

    def test_maps_are_page_aligned(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        # Odd-sized region still produces a page-aligned vaddr.
        mr = MemoryRegion(sdf, "mr", 0xABC)
        m = pd.create_automap(mr, "rw")
        assert m.vaddr % 0x1000 == 0

    def test_maps_do_not_overlap(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        sizes = [0x1000, 0x2000, 0x1000, 0x3000, 0x1000]
        for i, size in enumerate(sizes):
            pd.create_automap(MemoryRegion(sdf, f"mr{i}", size), "rw")

        for i, m1 in enumerate(pd.maps):
            for m2 in pd.maps[i + 1 :]:
                assert not (m1.vaddr < m2.end_vaddr and m2.vaddr < m1.end_vaddr)

    def test_guard_page_between_consecutive_maps(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        m1 = pd.create_automap(MemoryRegion(sdf, "mr1", 0x1000), "rw")
        m2 = pd.create_automap(MemoryRegion(sdf, "mr2", 0x1000), "rw")
        assert m2.vaddr >= m1.end_vaddr + 0x1000

    def test_fills_gap_near_start_vaddr(self, sdf):
        # A lone map far above start should leave the region near start_vaddr
        # available; the next automap must use it rather than append at the end.
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        far_map = Map(
            MemoryRegion(sdf, "far", 0x1000),
            pd.map_start_vaddr + 0x10_000_000,
            "rw",
        )
        pd.add_map(far_map)

        m = pd.create_automap(MemoryRegion(sdf, "gap", 0x1000), "rw")
        assert m.vaddr == pd.map_start_vaddr
        assert m.vaddr % 0x1000 == 0

    def test_fills_gap_between_existing_maps(self, sdf):
        pd = ProtectionDomain(sdf, "test", "test.elf", priority=100)
        mr1 = MemoryRegion(sdf, "mr1", 0x1000)
        mr2 = MemoryRegion(sdf, "mr2", 0x1000)
        gap_mr = MemoryRegion(sdf, "gap", 0x1000)

        m1 = Map(mr1, pd.map_start_vaddr, "rw")
        m2 = Map(mr2, pd.map_start_vaddr + 0x1000 + 0x10_000_000, "rw")
        pd.add_map(m1)
        pd.add_map(m2)

        m = pd.create_automap(gap_mr, "rw")
        assert m.vaddr >= m1.end_vaddr + 0x1000
        assert m.end_vaddr + 0x1000 <= m2.vaddr
