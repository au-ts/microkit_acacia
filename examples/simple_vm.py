# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from acacia.arch import aarch64
from acacia import (
    System,
    ProtectionDomain,
    MemoryRegion,
    Map,
    VirtualMachine,
    SchedulingProperties,
)

sdf = System(aarch64, paddr_top=0x10000)

vmm = ProtectionDomain(sdf, "vmm", "vmm.elf", priority=254, cpu=0)
vm_ram = MemoryRegion(sdf, "vm_ram", 0x40000000)

vcpu0 = VirtualMachine.VCPU(id=0, cpu=0)
vcpu1 = VirtualMachine.VCPU(id=1)

guest = VirtualMachine(
    name="linux_guest",
    scheduling=SchedulingProperties(priority=100),
    vcpus=[vcpu0, vcpu1],
)

# Map RAM into guest's address space
guest.add_map(Map(vm_ram, 0x40000000, "rw"))

# Attach VM to VMM (one VM per PD max)
vmm.add_vm(guest)

sdf.write_xml_file("simple_vm.system")
