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
    build_hook,
)
from acacia.arch import aarch64


class DummyClock(Subsystem):
    def __init__(self, sdf: System, prio: int):
        super().__init__(sdf, "clk")
        self.sdf = sdf
        # Make driver
        self.driver = ProtectionDomain(
            sdf,
            "clk_driver",
            "clk_driver.elf",
            scheduling=SchedulingProperties(prio, passive=True),
        )

    @build_hook
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
                self.sdf,
                Channel.End(c, can_notify=False, can_pp=True),
                Channel.End(self.driver, can_notify=False, can_pp=False),
            )


class DummyTimer(Subsystem):
    def __init__(self, sdf: System):
        super().__init__(sdf, "timer")
        self.sdf = sdf
        self.driver = None
        self.construct_infrastructure(199)

    @build_hook
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
                self.sdf,
                Channel.End(c, can_notify=False, can_pp=True),
                Channel.End(self.driver, can_notify=True, can_pp=False),
            )

    def construct_infrastructure(self, prio):
        # Make driver
        self.driver = ProtectionDomain(
            self.sdf,
            "timer_driver",
            "timer_driver.elf",
            scheduling=SchedulingProperties(prio, passive=True),
        )


class DummyI2C(Subsystem):
    def __init__(self, sdf: System):
        super().__init__(sdf, "i2c")
        self.driver = None
        self.virt = None
        self.sdf = sdf
        self.construct_infrastructure(198)

    @build_hook
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
                self.sdf,
                Channel.End(c, can_notify=False, can_pp=True),
                Channel.End(self.virt, can_notify=True, can_pp=False),
            )

    def construct_infrastructure(self, prio):
        # Make driver
        self.driver = ProtectionDomain(
            self.sdf,
            "i2c_driver",
            "i2c_driver.elf",
            scheduling=SchedulingProperties(prio),
        )
        self.virt = ProtectionDomain(
            self.sdf,
            "i2c_virt",
            "i2c_virt.elf",
            scheduling=SchedulingProperties(prio - 1),
        )
        d_v_ch = Channel(
            self.sdf,
            Channel.End(self.virt, can_notify=True, can_pp=False),
            Channel.End(self.driver, can_notify=True, can_pp=False),
        )


# Make system and subsystems
sdf = System(aarch64, paddr_top=0x100000000)

i2c = DummyI2C(sdf)
timer = DummyTimer(sdf)
clk = DummyClock(sdf, 201)

# Client
client = ProtectionDomain(sdf, "client", "client.elf", priority=1)
i2c.add_client(client)
timer.add_client(client)

sdf.write_xml_file("dummysubsystems.system")
