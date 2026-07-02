# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from acacia import (
    ProtectionDomain,
    Subsystem,
    Channel,
    Map,
    MemoryRegion,
    System,
    SchedulingProperties,
)
from acacia.arch import aarch64


class DummyClock(Subsystem):
    def __init__(self, prio):
        super().__init__("clk")
        self.driver = None
        # Make driver
        self.driver = ProtectionDomain(
            "clk_driver",
            "clk_driver.elf",
            scheduling=SchedulingProperties(prio, passive=True),
        )
        self.pds.append(self.driver)

    def connect_clients(self):
        assert self.driver is not None
        # Clients are connected with a channel allowing PPs and nothing else
        for c in self.clients:
            if c.priority >= self.driver.priority:
                raise SubsystemBuildError(
                    f"Client {c} has a priority higher "
                    f"than driver's ({self.driver.priority})!"
                )
            # Make channel
            ch = Channel(
                Channel.End(c, can_notify=False, can_pp=True),
                Channel.End(self.driver, can_notify=False, can_pp=False),
            )
            self.channels.append(ch)


class DummyTimer(Subsystem):
    def __init__(self):
        super().__init__("timer")
        self.driver = None
        self.construct_infrastructure(199)

    def connect_clients(self):
        assert self.driver is not None
        # Clients are connected with a channel allowing PPs and nothing else
        for c in self.clients:
            if c.priority >= self.driver.priority:
                raise RuntimeError(
                    f"Client {c} has a priority higher "
                    f"than driver's ({self.driver.priority})!"
                )
            # Make channel
            ch = Channel(
                Channel.End(c, can_notify=False, can_pp=True),
                Channel.End(self.driver, can_notify=True, can_pp=False),
            )
            self.channels.append(ch)

    def construct_infrastructure(self, prio):
        # Make driver
        self.driver = ProtectionDomain(
            "timer_driver",
            "timer_driver.elf",
            scheduling=SchedulingProperties(prio, passive=True),
        )
        self.pds.append(self.driver)


class DummyI2C(Subsystem):
    def __init__(self):
        super().__init__("i2c")
        self.driver = None
        self.virt = None
        self.construct_infrastructure(198)

    def connect_clients(self):
        assert self.driver is not None and self.virt is not None
        # Clients are connected with a channel allowing PPs and nothing else
        for c in self.clients:
            if c.priority >= self.virt.priority:
                raise SubsystemBuildError(
                    f"Client {c} has a priority higher "
                    f"than virt's ({self.virt.priority})!"
                )
            # Make channel
            ch = Channel(
                Channel.End(c, can_notify=False, can_pp=True),
                Channel.End(self.virt, can_notify=True, can_pp=False),
            )
            self.channels.append(ch)

    def construct_infrastructure(self, prio):
        # Make driver
        self.driver = ProtectionDomain(
            "i2c_driver", "i2c_driver.elf", scheduling=SchedulingProperties(prio)
        )
        self.virt = ProtectionDomain(
            "i2c_virt", "i2c_virt.elf", scheduling=SchedulingProperties(prio - 1)
        )
        d_v_ch = Channel(
            Channel.End(self.virt, can_notify=True, can_pp=False),
            Channel.End(self.driver, can_notify=True, can_pp=False),
        )
        self.channels.append(d_v_ch)
        self.pds.extend([self.driver, self.virt])


# Make system and subsystems
sdf = System(aarch64, paddr_top=0x100000000)

i2c = DummyI2C()
timer = DummyTimer()
clk = DummyClock(201)

# Client
client = ProtectionDomain("client", "client.elf", priority=1)
i2c.add_client(client)
timer.add_client(client)

# Build!
for s in [i2c, timer, clk]:
    sdf.add_subsystem(s)

sdf.resolve_subsystems()
for p in sdf.pds:
    print(p)

sdf.write_xml_file("dummysubsystems.system")
