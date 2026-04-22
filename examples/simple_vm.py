# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from sdfgenpy.arch import aarch64
from sdfgenpy import System, ProtectionDomain, MemoryRegion, Map, VirtualMachine, SchedulingProperties

sdf = System(aarch64, 0x10000)

vmm = ProtectionDomain("vmm", "vmm.elf", priority=254, cpu=0)
vm_ram = MemoryRegion("vm_ram", 0x40000000)
sdf.add_memory_region(vm_ram)

vcpu0 = VirtualMachine.VCPU(id=0, cpu=0)
vcpu1 = VirtualMachine.VCPU(id=1)

guest = VirtualMachine(
    name="linux_guest",
    scheduling=SchedulingProperties(priority=100),
    vcpus=[vcpu0, vcpu1]
)

# Map RAM into guest's address space
guest.add_map(Map(vm_ram, 0x40000000, "rw"))

# Attach VM to VMM (one VM per PD max)
vmm.set_vm(guest)

sdf.add_pd(vmm)

sdf.write_xml_file("simple_vm.system")
