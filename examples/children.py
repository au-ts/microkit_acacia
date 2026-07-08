# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from acacia.arch import aarch64
from acacia import ProtectionDomain, MemoryRegion, Map, System, Channel
import xml.etree.ElementTree as et

sdf = System(aarch64, paddr_top=0x10000)

parent = ProtectionDomain(sdf, "driver", "driver.elf", priority=200)
client_a = ProtectionDomain(sdf, "client_a", "client_a.elf", priority=100)
client_b = ProtectionDomain(sdf, "client_b", "client_b.elf", priority=100)

parent.add_child_pd(client_a)
parent.add_child_pd(client_b, child_id=5)

shm = MemoryRegion(sdf, "shm", 0x1000)
parent.add_map(Map(shm, 0x40000000, "rw"))
client_a.add_map(Map(shm, 0x40000000, "r"))
client_b.add_map(Map(shm, 0x40000000, "rw"))

# Channel between sibling PDs
ch = Channel(
    sdf,
    Channel.End(pd=client_a, can_notify=True, can_pp=False),
    Channel.End(pd=client_b, can_notify=True, can_pp=False),
)
sdf.add_channel(ch)

# Only add parent to system
sdf.add_pd(parent)

sdf.write_xml_file("children.system")
