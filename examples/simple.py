# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from sdfgenpy.arch import aarch64
from sdfgenpy import ProtectionDomain, MemoryRegion, Map, ConventionalIRQ, System
import xml.etree.ElementTree as et

sdf = System(aarch64, 0x10000)

serial_driver = ProtectionDomain("serial_driver", "serial_driver.elf", priority=200)
serial_virt_tx = ProtectionDomain(
    "serial_virt_tx", "serial_virt_tx.elf", priority=199
)

clk_driver = ProtectionDomain("clk_driver", "clk_driver.elf", priority=240)

timer_driver = ProtectionDomain("timer_driver", "timer_driver.elf", priority=254)
i2c_driver = ProtectionDomain("i2c_driver", "i2c_driver.elf", priority=3)
i2c_virt = ProtectionDomain("i2c_virt", "i2c_virt.elf", priority=2)
client_pn532 = ProtectionDomain("client_pn532", "client_pn532.elf", priority=1)
client_ds3231 = ProtectionDomain("client_ds3231", "client_ds3231.elf", priority=1)

clk_ccm_mr = MemoryRegion("clk_ccm", 0xd000, paddr=0x30380000)
clk_ccm_analog_mr = MemoryRegion("clk_ccm_analog", 0x1000, paddr=0x30360000)
sdf.add_memory_region(clk_ccm_mr)
sdf.add_memory_region(clk_ccm_analog_mr)
clk_ccm_map = Map(clk_ccm_mr, 0x3200000, "rw")
clk_ccm_analog_map = Map(clk_ccm_analog_mr, 0x3300000, "rw")
clk_driver.add_map(clk_ccm_map)
clk_driver.add_map(clk_ccm_analog_map)


# i2c_system = Sddf.I2c(sdf, i2c_node, i2c_driver, i2c_virt)
# i2c_system.add_client(client_ds3231)
# i2c_system.add_client(client_pn532)
#
# timer_system = Sddf.Timer(sdf, timer_node, timer_driver)
# timer_system.add_client(client_pn532)
# timer_system.add_client(client_ds3231)

# serial_system = Sddf.Serial(
#     sdf, serial_node, serial_driver, serial_virt_tx, enable_color=False
# )
# serial_system.add_client(client_pn532)
# serial_system.add_client(client_ds3231)

pds = [
    serial_driver,
    serial_virt_tx,
    timer_driver,
    clk_driver,
    i2c_driver,
    i2c_virt,
    client_pn532,
    client_ds3231,
]
for pd in pds:
    sdf.add_pd(pd)

# assert i2c_system.connect()
# assert i2c_system.serialise_config(output_dir)
# assert serial_system.connect()
# assert serial_system.serialise_config(output_dir)
# assert timer_system.connect()
# assert timer_system.serialise_config(output_dir)

# Make element tree and indent
xml = sdf.render()
et.indent(xml, level=0)

tree = et.ElementTree(xml)
et.indent(tree, space='\t', level=0)
tree.write("simple.system", encoding="utf-8", xml_declaration=True)
