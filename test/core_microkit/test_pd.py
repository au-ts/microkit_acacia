# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from acacia.pd import ProtectionDomain, SchedulingProperties, MAX_IDS, VirtualMachine
from acacia.memory import MemoryRegion, Map


class TestSchedulingProperties:
    def test_priority_required(self):
        with pytest.raises(ValueError, match="Must define a non-negative priority"):
            SchedulingProperties(priority=None)

    def test_negative_priority_rejected(self):
        with pytest.raises(ValueError, match="Must define a non-negative priority"):
            SchedulingProperties(priority=-1)

    def test_negative_budget_rejected(self):
        with pytest.raises(ValueError, match="SchedulingProperties cannot be negative!"):
            SchedulingProperties(priority=100, budget=-10, period=100)

    def test_budget_exceeds_period_rejected(self):
        with pytest.raises(ValueError, match="Budget must be defined and cannot be greater than period"):
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
        for i in range(MAX_IDS):
            pd.allocate_id()
        # Should fail to allocate any more
        with pytest.raises(StopIteration):
            id_val = pd.allocate_id()


class TestProtectionDomainIrq:
    def test_add_irq_allocates_id(self):
        from acacia.irq import ConventionalIRQ
        pd = ProtectionDomain("test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=None)
        pd.add_irq(irq)
        assert irq.id is not None
        assert irq.id in pd.assigned_ids

    def test_add_irq_specific_id(self):
        from acacia.irq import ConventionalIRQ
        pd = ProtectionDomain("test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=7)
        pd.add_irq(irq)
        assert irq.id == 7

    def test_add_same_irq_twice_rejected(self):
        from acacia.irq import ConventionalIRQ
        pd = ProtectionDomain("test", "test.elf", priority=100)
        irq = ConventionalIRQ(42, ConventionalIRQ.Trigger.EDGE, id=None)
        pd.add_irq(irq)
        with pytest.raises(RuntimeError, match="same IRQ"):
            pd.add_irq(irq)

class TestChildPdAllocation:
    def test_allocate_child_id_auto(self):
        pd = ProtectionDomain("parent", "parent.elf", priority=100)
        id1 = pd.allocate_child_pd_id()
        id2 = pd.allocate_child_pd_id()
        assert id1 != id2
        assert id1 in pd.assigned_child_ids
        assert id2 in pd.assigned_child_ids
        assert id1 >= 0 and id1 < MAX_IDS

    def test_allocate_child_id_specific(self):
        pd = ProtectionDomain("parent", "parent.elf", priority=100)
        id_val = pd.allocate_child_pd_id(requested_id=7)
        assert id_val == 7
        assert 7 in pd.assigned_child_ids

    def test_allocate_child_id_duplicate_rejected(self):
        pd = ProtectionDomain("parent", "parent.elf", priority=100)
        pd.allocate_child_pd_id(requested_id=5)
        with pytest.raises(RuntimeError, match="not available"):
            pd.allocate_child_pd_id(requested_id=5)

    def test_child_id_namespace_separate_from_irq(self):
        """Child PD IDs and IRQ IDs should not conflict"""
        pd = ProtectionDomain("parent", "parent.elf", priority=100)
        irq_id = pd.allocate_id(requested_id=3)
        child_id = pd.allocate_child_pd_id(requested_id=3)
        assert irq_id == 3
        assert child_id == 3
        assert pd.assigned_ids == [3]
        assert pd.assigned_child_ids == [3]


class TestChildPdAddition:
    def test_add_child_auto_id(self):
        parent = ProtectionDomain("parent", "parent.elf", priority=100)
        child = ProtectionDomain("child", "child.elf", priority=50)
        parent.add_child_pd(child)
        assert child.child_id is not None
        assert child in parent.children
        assert child.child_id in parent.assigned_child_ids

    def test_add_child_specific_id(self):
        parent = ProtectionDomain("parent", "parent.elf", priority=100)
        child = ProtectionDomain("child", "child.elf", priority=50)
        parent.add_child_pd(child, child_id=10)
        assert child.child_id == 10

    def test_add_same_child_twice_rejected(self):
        parent = ProtectionDomain("parent", "parent.elf", priority=100)
        child = ProtectionDomain("child", "child.elf", priority=50)
        parent.add_child_pd(child)
        with pytest.raises(RuntimeError, match="same PD"):
            parent.add_child_pd(child)

    def test_add_child_max_ids_exhausted(self):
        parent = ProtectionDomain("parent", "parent.elf", priority=100)
        # Fill up all child slots
        for i in range(MAX_IDS):
            child = ProtectionDomain(f"child_{i}", f"child_{i}.elf", priority=50)
            parent.add_child_pd(child)

        # Next one should fail when trying to find next available
        extra_child = ProtectionDomain("extra", "extra.elf", priority=50)
        with pytest.raises(StopIteration):  # next() fails when all ids used
            parent.add_child_pd(extra_child)


class TestChildPdRendering:
    def test_child_rendered_as_nested_element(self):
        parent = ProtectionDomain("parent", "parent.elf", priority=100)
        child = ProtectionDomain("child", "child.elf", priority=50)
        parent.add_child_pd(child, child_id=2)

        root = et.Element("system")
        parent.render(root)

        parent_elem = root.find("protection_domain")
        assert parent_elem.get("name") == "parent"

        child_elem = parent_elem.find("protection_domain")
        assert child_elem is not None
        assert child_elem.get("name") == "child"
        assert child_elem.get("id") == "2"

    def test_child_without_parent_no_id_attribute(self):
        child = ProtectionDomain("child", "child.elf", priority=50)
        root = et.Element("system")
        child.render(root)

        child_elem = root.find("protection_domain")
        assert child_elem.get("id") is None

    def test_multiple_children_rendered(self):
        parent = ProtectionDomain("parent", "parent.elf", priority=100)
        child1 = ProtectionDomain("child1", "child1.elf", priority=50)
        child2 = ProtectionDomain("child2", "child2.elf", priority=50)

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

    def test_nested_grandchildren(self):
        grandparent = ProtectionDomain("gp", "gp.elf", priority=200)
        parent = ProtectionDomain("parent", "parent.elf", priority=100)
        child = ProtectionDomain("child", "child.elf", priority=50)

        grandparent.add_child_pd(parent, child_id=1)
        parent.add_child_pd(child, child_id=1)  # Different namespace, same number allowed

        root = et.Element("system")
        grandparent.render(root)

        gp_elem = root.find("protection_domain")
        parent_elem = gp_elem.find("protection_domain")
        child_elem = parent_elem.find("protection_domain")

        assert gp_elem.get("id") is None  # Top level
        assert parent_elem.get("id") == "1"
        assert child_elem.get("id") == "1"


class TestChildPdIntegration:
    def test_child_with_maps_and_irqs(self):
        from acacia.irq import ConventionalIRQ

        parent = ProtectionDomain("parent", "parent.elf", priority=100)
        child = ProtectionDomain("child", "child.elf", priority=50)
        parent.add_child_pd(child, child_id=3)

        mr = MemoryRegion("test_mr", 0x1000)
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
        vm = VirtualMachine("vm1", SchedulingProperties(priority=100), vcpus=v)
        assert isinstance(vm.vcpus, list)
        assert len(vm.vcpus) == 1

    def test_init_with_vcpu_list(self):
        vcpus = [VirtualMachine.VCPU(id=0), VirtualMachine.VCPU(id=1)]
        vm = VirtualMachine("vm2", SchedulingProperties(priority=100), vcpus=vcpus)
        assert len(vm.vcpus) == 2

    def test_duplicate_vcpu_ids_rejected(self):
        vcpus = [VirtualMachine.VCPU(id=0), VirtualMachine.VCPU(id=0)]
        with pytest.raises(RuntimeError, match="unique per VM"):
            VirtualMachine("vm3", SchedulingProperties(priority=100), vcpus=vcpus)

    def test_too_many_vcpus_rejected(self):
        vcpus = [VirtualMachine.VCPU(id=i) for i in range(63)]  # MAX_IDS is 62
        with pytest.raises(RuntimeError, match="supported at max"):
            VirtualMachine("vm4", SchedulingProperties(priority=100), vcpus=vcpus)

    def test_vm_inherits_entity_maps(self):
        vm = VirtualMachine("vm5", SchedulingProperties(priority=100), vcpus=VirtualMachine.VCPU(id=0))
        mr = MemoryRegion("test_mr", 0x1000)
        m = Map(mr, 0x40000000, "rw")
        vm.add_map(m)
        assert len(vm.maps) == 1

    def test_vm_render_structure(self):
        vm = VirtualMachine("guest", SchedulingProperties(priority=50, budget=1000, period=2000), vcpus=[VirtualMachine.VCPU(id=0), VirtualMachine.VCPU(id=1)])
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
    def test_set_vm_success(self):
        pd = ProtectionDomain("vmm", "vmm.elf", priority=254)
        vm = VirtualMachine("guest", SchedulingProperties(priority=100), vcpus=VirtualMachine.VCPU(id=0))
        pd.set_vm(vm)
        assert pd.vm is vm

    def test_set_vm_twice_rejected(self):
        pd = ProtectionDomain("vmm", "vmm.elf", priority=254)
        vm1 = VirtualMachine("guest1", SchedulingProperties(priority=100), vcpus=VirtualMachine.VCPU(id=0))
        vm2 = VirtualMachine("guest2", SchedulingProperties(priority=100), vcpus=VirtualMachine.VCPU(id=1))
        pd.set_vm(vm1)
        with pytest.raises(RuntimeError, match="Can only have one VM per PD!"):
            pd.set_vm(vm2)

    def test_vm_rendered_inside_pd(self):
        pd = ProtectionDomain("vmm", "vmm.elf", priority=254)
        vm = VirtualMachine("guest", SchedulingProperties(priority=100), vcpus=VirtualMachine.VCPU(id=0))
        pd.set_vm(vm)
        root = et.Element("system")
        pd.render(root)
        pd_elem = root.find("protection_domain")
        vm_elem = pd_elem.find("virtual_machine")
        assert vm_elem is not None
        assert vm_elem.get("name") == "guest"

    def test_vm_with_maps_rendered(self):
        pd = ProtectionDomain("vmm", "vmm.elf", priority=254)
        mr = MemoryRegion("ram", 0x1000)
        vm = VirtualMachine("guest", SchedulingProperties(priority=100), vcpus=VirtualMachine.VCPU(id=0))
        vm.add_map(Map(mr, 0x40000000, "rw"))
        pd.set_vm(vm)
        root = et.Element("system")
        pd.render(root)
        vm_elem = root.find("protection_domain").find("virtual_machine")
        map_elem = vm_elem.find("map")
        assert map_elem is not None
        assert map_elem.get("vaddr") == "0x40000000"
