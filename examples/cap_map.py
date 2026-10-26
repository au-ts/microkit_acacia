# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from acacia.arch import aarch64
from acacia import (
    ProtectionDomain,
    System,
    TCBCapMap,
)

sdf = System(aarch64, paddr_top=0x10000)

server = ProtectionDomain(sdf, "server", "server.elf", priority=200)
client = ProtectionDomain(sdf, "client", "client.elf", priority=199)

server.add_cap_map(TCBCapMap(1, client))

sdf.write_xml_file("cap_map.system")
