# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from sdfgenpy.arch import x86_64
from sdfgenpy import ProtectionDomain, MemoryRegion, Map, System, Channel
from sdfgenpy.x86 import IrqIoapic, IrqMsi, IOPort
import xml.etree.ElementTree as et

sdf = System(x86_64, 0x10000)

# PDs
net_driver = ProtectionDomain("net_driver", "net_driver.elf", priority=200)

serial_driver = ProtectionDomain("serial_driver", "serial_driver.elf", priority=199)

timer_driver = ProtectionDomain("timer_driver", "timer_driver.elf", priority=254)

net_virt = ProtectionDomain("net_virt", "net_virt.elf", priority=198)

# dummy clients
client_http = ProtectionDomain("client_http", "client_http.elf", priority=1)
client_dns = ProtectionDomain("client_dns", "client_dns.elf", priority=1)

# Channels
ch_http = Channel(
    Channel.End(pd=client_http, can_notify=True, can_pp=True),
    Channel.End(pd=net_virt, can_notify=True, can_pp=False)
)

ch_dns = Channel(
    Channel.End(pd=client_dns, can_notify=True, can_pp=True),
    Channel.End(pd=net_virt, can_notify=True, can_pp=False)
)

ch_timer_http = Channel(
    Channel.End(pd=client_http, can_notify=False, can_pp=True),
    Channel.End(pd=timer_driver, can_notify=True, can_pp=False)
)

ch_timer_dns = Channel(
    Channel.End(pd=client_dns, can_notify=False, can_pp=True),
    Channel.End(pd=timer_driver, can_notify=True, can_pp=False)
)

sdf.add_channel(ch_http)
sdf.add_channel(ch_dns)
sdf.add_channel(ch_timer_http)
sdf.add_channel(ch_timer_dns)

# MRs
net_mmio = MemoryRegion("net_mmio", 0x4000, paddr=0xfeb00000)
serial_mmio = MemoryRegion("serial_mmio", 0x1000, paddr=0xfeb40000)
sdf.add_memory_region(net_mmio)
sdf.add_memory_region(serial_mmio)

# Maps
net_map = Map(net_mmio, 0x2000000, "rw")
serial_map = Map(serial_mmio, 0x2100000, "rw")
net_driver.add_map(net_map)
serial_driver.add_map(serial_map)

# IOAPIC interrupts
# IOAPIC 0, pin 4, vector 32, active high, edge triggered
# (resembles old school serial)
serial_irq = IrqIoapic(
    ioapic_id=0,
    pin=4,
    vector=32,
    trigger=IrqIoapic.Trigger.EDGE,
    polarity=IrqIoapic.Polarity.ACTIVEHIGH
)

# try level triggered
timer_irq = IrqIoapic(
    ioapic_id=0,
    pin=2,
    vector=48,
    trigger=IrqIoapic.Trigger.LEVEL,
    polarity=IrqIoapic.Polarity.ACTIVEHIGH
)

# MSI interrupts
net_msi_irq = IrqMsi(
    pci_bus=0,
    pci_device=3,
    pci_func=0,
    vector=64,
    handle=0
)

serial_driver.add_irq(serial_irq)
timer_driver.add_irq(timer_irq)
net_driver.add_irq(net_msi_irq)

# add IOport for testing
serial_ioport = IOPort(addr=0x3f8, size=0x8)  # COM1: 0x3F8-0x3FF
serial_driver.add_ioport(serial_ioport)

pds = [
    net_driver,
    serial_driver,
    timer_driver,
    net_virt,
    client_http,
    client_dns,
]
for pd in pds:
    sdf.add_pd(pd)

xml = sdf.render()
et.indent(xml, level=0)

tree = et.ElementTree(xml)
et.indent(tree, space='\t', level=0)
tree.write("simple_x86.system", encoding="utf-8", xml_declaration=True)

