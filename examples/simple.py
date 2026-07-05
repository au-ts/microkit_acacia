# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from acacia.arch import aarch64
from acacia import (
    ProtectionDomain,
    MemoryRegion,
    Map,
    ConventionalIRQ,
    IRQ,
    System,
    Channel,
)
import xml.etree.ElementTree as et

sdf = System(aarch64, paddr_top=0x10000)

serial_driver = ProtectionDomain(
    "serial_driver", "serial_driver.elf", sdf, priority=200
)
serial_virt_tx = ProtectionDomain(
    "serial_virt_tx", "serial_virt_tx.elf", sdf, priority=199
)

clk_driver = ProtectionDomain("clk_driver", "clk_driver.elf", sdf, priority=240)
timer_driver = ProtectionDomain("timer_driver", "timer_driver.elf", sdf, priority=254)

i2c_driver = ProtectionDomain("i2c_driver", "i2c_driver.elf", sdf, priority=3)
i2c_virt = ProtectionDomain("i2c_virt", "i2c_virt.elf", sdf, priority=2)

client_pn532 = ProtectionDomain("client_pn532", "client_pn532.elf", sdf, priority=1)
client_ds3231 = ProtectionDomain("client_ds3231", "client_ds3231.elf", sdf, priority=1)

ch_pn532 = Channel(
    Channel.End(pd=client_pn532, can_notify=True, can_pp=True),
    Channel.End(pd=i2c_virt, can_notify=True, can_pp=False),
    sdf,
)

ch_ds3231 = Channel(
    Channel.End(pd=client_ds3231, can_notify=True, can_pp=True),
    Channel.End(pd=i2c_virt, can_notify=True, can_pp=False),
    sdf,
)

ch_timer_ds3231 = Channel(
    Channel.End(pd=client_ds3231, can_notify=False, can_pp=True),
    Channel.End(pd=timer_driver, can_notify=True, can_pp=False),
    sdf,
)

ch_timer_pn532 = Channel(
    Channel.End(pd=client_pn532, can_notify=False, can_pp=True),
    Channel.End(pd=timer_driver, can_notify=True, can_pp=False),
    sdf,
)
sdf.add_channel(ch_ds3231)
sdf.add_channel(ch_pn532)
sdf.add_channel(ch_timer_ds3231)
sdf.add_channel(ch_timer_pn532)

clk_ccm_mr = MemoryRegion("clk_ccm", 0xD000, sdf, paddr=0x30380000)
clk_ccm_analog_mr = MemoryRegion("clk_ccm_analog", 0x1000, sdf, paddr=0x30360000)
sdf.add_memory_region(clk_ccm_mr)
sdf.add_memory_region(clk_ccm_analog_mr)
clk_ccm_map = Map(clk_ccm_mr, 0x3200000, "rw")
clk_ccm_analog_map = Map(clk_ccm_analog_mr, 0x3300000, "rw")
clk_driver.add_map(clk_ccm_map)
clk_driver.add_map(clk_ccm_analog_map)

# Add dummy interrupts
clk_irq = ConventionalIRQ(0, 15, IRQ.Trigger.EDGE)
i2c_irq = ConventionalIRQ(1, 16, IRQ.Trigger.LEVEL)

clk_driver.add_irq(clk_irq)
i2c_driver.add_irq(i2c_irq)

sdf.write_xml_file("simple.system")
