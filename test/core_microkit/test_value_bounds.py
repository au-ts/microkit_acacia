# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

"""
Sizes, addresses, etc. that cannot be negative / must be positive
must be rejected when the object is constructed
"""

import pytest

from acacia.arch import aarch64
from acacia.irq import IRQ, ConventionalIRQ, IrqIoapic, IrqMsi
from acacia.memory import IOMap, Map, MemoryRegion
from acacia.pd import Entity, ProtectionDomain, SchedulingProperties, VirtualMachine
from acacia.system import System
from acacia.util import require_non_negative, require_positive
from acacia.x86 import IOPort


@pytest.fixture
def sdf():
    return System(aarch64, paddr_top=0x10000000)


class TestHelpers:
    def test_require_non_negative(self):
        require_non_negative(0, "x")
        require_non_negative(1, "x")
        with pytest.raises(ValueError, match="x must be non-negative, got -1"):
            require_non_negative(-1, "x")

    def test_require_positive(self):
        require_positive(1, "x")
        for bad in (0, -1):
            with pytest.raises(ValueError, match=f"x must be positive.*got {bad}"):
                require_positive(bad, "x")


class TestSystem:
    @pytest.mark.parametrize("paddr_top", [0, -0x1000])
    def test_paddr_top_must_be_positive(self, paddr_top):
        with pytest.raises(ValueError, match="paddr_top must be positive"):
            System(aarch64, paddr_top=paddr_top)


class TestMemory:
    @pytest.mark.parametrize("size", [0, -0x1000])
    def test_mr_size_must_be_positive(self, sdf, size):
        with pytest.raises(ValueError, match="MemoryRegion size must be positive"):
            MemoryRegion(sdf, "mr", size)

    def test_iomap_zero_iovaddr_allowed(self, sdf):
        mr = MemoryRegion(sdf, "mr", 0x1000)
        assert IOMap(mr, 0).iovaddr == 0

    def test_map_zero_vaddr_allowed(self, sdf):
        mr = MemoryRegion(sdf, "mr", 0x1000)
        assert Map(mr, 0, "r").vaddr == 0


class TestIOPort:
    def test_valid(self):
        iop = IOPort(0, 1, id=0)
        assert (iop.addr, iop.size, iop.id) == (0, 1, 0)

    def test_negative_addr_rejected(self):
        with pytest.raises(ValueError, match="IOPort addr must be non-negative"):
            IOPort(-1, 4)

    @pytest.mark.parametrize("size", [0, -4])
    def test_size_must_be_positive(self, size):
        with pytest.raises(ValueError, match="IOPort size must be positive"):
            IOPort(0x3F8, size)

    def test_negative_id_rejected(self):
        with pytest.raises(ValueError, match="IOPort id must be non-negative"):
            IOPort(0x3F8, 8, id=-1)


class TestIRQs:
    def test_conventional_negative_number_rejected(self):
        with pytest.raises(ValueError, match="IRQ number must be non-negative"):
            ConventionalIRQ(-1, IRQ.Trigger.EDGE)

    def test_conventional_negative_id_rejected(self):
        with pytest.raises(ValueError, match="IRQ id must be non-negative"):
            ConventionalIRQ(42, IRQ.Trigger.EDGE, id=-1)

    def test_conventional_zero_allowed(self):
        irq = ConventionalIRQ(0, IRQ.Trigger.EDGE, id=0)
        assert (irq.irq_num, irq.id) == (0, 0)

    @pytest.mark.parametrize(
        "kwargs, what",
        [
            (dict(ioapic_id=-1, pin=4, vector=32), "IOAPIC id"),
            (dict(ioapic_id=0, pin=-1, vector=32), "IOAPIC pin"),
            (dict(ioapic_id=0, pin=4, vector=-1), "IRQ vector"),
            (dict(ioapic_id=0, pin=4, vector=32, id=-1), "IRQ id"),
        ],
    )
    def test_ioapic_negative_rejected(self, kwargs, what):
        with pytest.raises(ValueError, match=f"{what} must be non-negative"):
            IrqIoapic(**kwargs)

    @pytest.mark.parametrize(
        "field, what",
        [
            ("pci_bus", "PCI bus"),
            ("pci_device", "PCI device"),
            ("pci_func", "PCI function"),
            ("vector", "IRQ vector"),
            ("handle", "MSI handle"),
            ("id", "IRQ id"),
        ],
    )
    def test_msi_negative_rejected(self, field, what):
        kwargs = dict(pci_bus=0, pci_device=0, pci_func=0, vector=0, handle=0, id=0)
        IrqMsi(**kwargs)  # all zeroes is valid
        kwargs[field] = -1
        with pytest.raises(ValueError, match=f"{what} must be non-negative"):
            IrqMsi(**kwargs)


class TestScheduling:
    @pytest.mark.parametrize("period", [0, -100])
    def test_period_must_be_positive(self, period):
        with pytest.raises(ValueError, match="period must be positive"):
            SchedulingProperties(priority=1, period=period, budget=1)

    @pytest.mark.parametrize("budget", [0, -100])
    def test_budget_must_be_positive(self, budget):
        with pytest.raises(ValueError, match="budget must be positive"):
            SchedulingProperties(priority=1, period=1000, budget=budget)

    def test_budget_without_period_must_be_positive(self):
        with pytest.raises(ValueError, match="budget must be positive"):
            SchedulingProperties(priority=1, budget=0)


class TestProtectionDomain:
    @pytest.mark.parametrize("stack_size", [0, -0x1000])
    def test_stack_size_must_be_positive(self, sdf, stack_size):
        with pytest.raises(ValueError, match="stack_size must be positive"):
            ProtectionDomain(sdf, "pd", "pd.elf", stack_size=stack_size)

    def test_negative_cpu_rejected(self, sdf):
        with pytest.raises(ValueError, match="PD cpu must be non-negative"):
            ProtectionDomain(sdf, "pd", "pd.elf", cpu=-1)

    def test_cpu_zero_allowed(self, sdf):
        assert ProtectionDomain(sdf, "pd", "pd.elf", cpu=0).cpu == 0

    def test_negative_requested_id_rejected(self, sdf):
        pd = ProtectionDomain(sdf, "pd", "pd.elf")
        with pytest.raises(ValueError, match="Requested id must be non-negative"):
            pd.allocate_id(-1)

    def test_negative_child_id_rejected(self, sdf):
        parent = ProtectionDomain(sdf, "parent", "parent.elf")
        child = ProtectionDomain(sdf, "child", "child.elf")
        with pytest.raises(ValueError, match="Child PD id must be non-negative"):
            parent.add_child_pd(child, child_id=-1)
        # Rejection must leave the child as a top-level PD.
        assert child in sdf.pds
        assert child.child_id is None

    def test_negative_map_start_vaddr_rejected(self):
        with pytest.raises(ValueError, match="map_start_vaddr must be non-negative"):
            Entity("e", None, map_start_vaddr=-0x1000)


class TestVCPU:
    def test_negative_cpu_rejected(self):
        with pytest.raises(ValueError, match="VCPU cpu must be non-negative"):
            VirtualMachine.VCPU(id=0, cpu=-1)

    def test_cpu_zero_allowed(self):
        assert VirtualMachine.VCPU(id=0, cpu=0).cpu == 0
