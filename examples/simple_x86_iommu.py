# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from acacia.arch import x86_64
from acacia import ProtectionDomain, MemoryRegion, Map, System, Channel
from acacia.irq import IrqIoapic, IrqMsi
from acacia.x86 import IOPort
from acacia.memory import IOAddressSpace, IOMap
import xml.etree.ElementTree as et

sdf = System(x86_64, paddr_top=0x10000)

# PDs
net_driver = ProtectionDomain(sdf, "net_driver", "net_driver.elf", priority=200)

serial_driver = ProtectionDomain(
    sdf, "serial_driver", "serial_driver.elf", priority=199
)

timer_driver = ProtectionDomain(sdf, "timer_driver", "timer_driver.elf", priority=254)

net_virt = ProtectionDomain(sdf, "net_virt", "net_virt.elf", priority=198)

# dummy clients
client_http = ProtectionDomain(sdf, "client_http", "client_http.elf", priority=1)
client_dns = ProtectionDomain(sdf, "client_dns", "client_dns.elf", priority=1)

# Channels
ch_http = Channel(
    sdf,
    Channel.End(pd=client_http, can_notify=True, can_pp=True),
    Channel.End(pd=net_virt, can_notify=True, can_pp=False),
)

ch_dns = Channel(
    sdf,
    Channel.End(pd=client_dns, can_notify=True, can_pp=True),
    Channel.End(pd=net_virt, can_notify=True, can_pp=False),
)

ch_timer_http = Channel(
    sdf,
    Channel.End(pd=client_http, can_notify=False, can_pp=True),
    Channel.End(pd=timer_driver, can_notify=True, can_pp=False),
)

ch_timer_dns = Channel(
    sdf,
    Channel.End(pd=client_dns, can_notify=False, can_pp=True),
    Channel.End(pd=timer_driver, can_notify=True, can_pp=False),
)

# MRs
net_mmio = MemoryRegion(sdf, "net_mmio", 0x4000, paddr=0xFEB00000)
serial_mmio = MemoryRegion(sdf, "serial_mmio", 0x1000, paddr=0xFEB40000)

# Maps
net_map = Map(net_mmio, 0x2000000, "rw")
serial_map = Map(serial_mmio, 0x2100000, "rw")
net_driver.add_map(net_map)
serial_driver.add_map(serial_map)

# IOMMU
net_iospace = IOAddressSpace(sdf, "net_iospace", "fee:fi.fo", "1")
net_iomap = IOMap(net_mmio, 0x34000000)
net_iospace.add_io_map(net_iomap)

# IOAPIC interrupts
# IOAPIC 0, pin 4, vector 32, active high, edge triggered
# (resembles old school serial)
serial_irq = IrqIoapic(
    ioapic_id=0,
    pin=4,
    vector=32,
    trigger=IrqIoapic.Trigger.EDGE,
    polarity=IrqIoapic.Polarity.ACTIVEHIGH,
)

# try level triggered
timer_irq = IrqIoapic(
    ioapic_id=0,
    pin=2,
    vector=48,
    trigger=IrqIoapic.Trigger.LEVEL,
    polarity=IrqIoapic.Polarity.ACTIVEHIGH,
)

# MSI interrupts
net_msi_irq = IrqMsi(pci_bus=0, pci_device=3, pci_func=0, vector=64, handle=0)

serial_driver.add_irq(serial_irq)
timer_driver.add_irq(timer_irq)
net_driver.add_irq(net_msi_irq)

# add IOport for testing
serial_ioport = IOPort(addr=0x3F8, size=0x8)  # COM1: 0x3F8-0x3FF
serial_driver.add_ioport(serial_ioport)

sdf.write_xml_file("simple_x86_iommu.system")
