# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from acacia import ProtectionDomain, Subsystem, Channel, Map, MemoryRegion, System, SchedulingProperties
from acacia.arch import aarch64
from acacia.configstruct import ConfigStruct, DeviceResourcesFactory, ConfigStructResolver
from acacia.irq import IRQ, ConventionalIRQ


class DummyI2C(Subsystem):
    def __init__(self, irq_type=ConventionalIRQ):
        super().__init__("i2c")
        self.driver = None
        self.magic = "dmi2c"
        self.irq_type = irq_type
        self.construct_infrastructure(200)

    def connect_clients(self):
        assert self.driver is not None
        # Clients are connected with a channel allowing PPs and nothing else
        for c in self.clients:
            if c.priority >= self.driver.priority:
                raise SubsystemBuildError(f"Client {c} has a priority higher "
                                          f"than driver's ({self.driver.priority})!")
            # Make channel
            ch = Channel(
                    Channel.End(c, can_notify=False, can_pp=True),
                    Channel.End(self.driver, can_notify=False, can_pp=False)
            )
            self.channels.append(ch)

    def construct_infrastructure(self, driver_prio: int):
        # Make driver
        self.driver = ProtectionDomain("i2c_driver", "i2c_driver.elf", scheduling=SchedulingProperties(driver_prio, passive=True))
        self.pds.append(self.driver)

        dev_mem = MemoryRegion("i2c_ctrl", 0x1000, paddr=0x37370000)
        self.mrs.append(dev_mem)
        dev_mem_map = Map(dev_mem, 0x10000000, Map.Permissions(r=True, w=True))
        self.dev_mem = dev_mem_map
        self.driver.add_map(dev_mem_map)

        dev_irq = self.irq_type(1, IRQ.Trigger.EDGE)
        self.irq_id = self.driver.add_irq(dev_irq)

    def generate_config_structs(self):
        # This is just for testing, so we take the laziest option.
        # 1. driver just needs resources, ignore real config structs
        # 2. clients just get their config struct
        devresource = DeviceResourcesFactory(self.magic, [self.dev_mem], [self.irq_id], self.driver.prog_image)
        print(f"dev = {devresource}")

        # clients just need a trivial config struct with channel
        def client_struct_factory(client_pd, n):
            end = next(x.end_a for x in self.channels if x.end_a.pd is client_pd)
            ch_id = end.ch_id
            fields = {
                    "driver_id": ch_id
            }
            return ConfigStruct("i2c_client_config_t", client_pd.prog_image, "i2c_client_config", fields=fields)

        # client_structs = [client_struct_factory(c,n) for n,c in enumerate(self.clients)]
        client_structs = []
        return [devresource] + client_structs

sdf = System(aarch64, 0x100000000)

i2c = DummyI2C()
client1 = ProtectionDomain("client1", "client1.elf", priority=1)
client2 = ProtectionDomain("client2", "client2.elf", priority=1)
client3 = ProtectionDomain("client3", "client3.elf", priority=1)

# Add a channel between two of the clients to check that channel mapping is correct.
# Clients 1 and 2 should have a configstruct with driver_id = 1
ch12 = Channel(
        Channel.End(client1, can_notify=True, can_pp=False),
        Channel.End(client2, can_notify=True, can_pp=False)
)
sdf.add_channel(ch12)

for c in [client1, client2, client3]:
    i2c.add_client(c)

sdf.add_subsystem(i2c)
sdf.resolve_subsystems()

structs = i2c.generate_config_structs()
r = ConfigStructResolver("./dummy_configstruct_build")
for s in structs:
    print(s)
    r.add_struct(s)

# Test struct dumper
dumper = r.dwarfdump
# dumper._parse_file(i2c.driver.prog_image)
# print("Typedef mappings for driver:")
# for k in dumper.file_typedef_to_type[i2c.driver.prog_image].keys():
#     print(f"\t{k} -> {dumper.file_typedef_to_type[i2c.driver.prog_image][k]} "
#           f"base_type={dumper.get_typedef_base_type(i2c.driver.prog_image, k)}")

# dumper._parse_file(client1.prog_image)
# print("Typedef mappings for client")
# for k in dumper.file_typedef_to_type[client1.prog_image].keys():
#     print(f"\t{k} -> {dumper.file_typedef_to_type[client1.prog_image][k]} "
#           f"base_type={dumper.get_typedef_base_type(client1.prog_image, k)}")

# print("\nList of all structs (driver):")
# for s in dumper.file_structs[i2c.driver.prog_image]:
#     print(f"\t{s}")
#     for m in dumper.file_structs[i2c.driver.prog_image][s].members:
#         print(f"\t\t{m}")

# Try resolve our config structs
print("Dwarf structs matching config of dummy i2c driver:")
driver_dwarf_structs = dumper.find_struct_and_children(i2c.driver.prog_image, structs[0].typedef_name)
print(driver_dwarf_structs)


# try find i2c configs structs
sdf.make_config_structs("./dummy_configstruct_build/")
