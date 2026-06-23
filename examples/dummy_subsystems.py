# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from acacia import ProtectionDomain, Subsystem, Channel, Map, MemoryRegion, System, SchedulingProperties
from acacia.subsystem import subsystem_register_dependency, get_dependency_map, forced_max_priority, SubsystemBuildError
from acacia.arch import aarch64

class DummyClock(Subsystem):
    def __init__(self, prio):
        super().__init__("clk")
        self.driver = None
        # Make driver
        self.driver = ProtectionDomain("clk_driver", "clk_driver.elf", scheduling=SchedulingProperties(prio, passive=True))
        self.pds.append(self.driver)


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



class DummyTimer(Subsystem):
    def __init__(self):
        super().__init__("timer")
        self.driver = None

    def connect_clients(self):
        assert self.driver is not None
        # Clients are connected with a channel allowing PPs and nothing else
        for c in self.clients:
            if c.priority >= self.driver.priority:
                raise RuntimeError(f"Client {c} has a priority higher "
                                          f"than driver's ({self.driver.priority})!")
            # Make channel
            ch = Channel(
                    Channel.End(c, can_notify=False, can_pp=True),
                    Channel.End(self.driver, can_notify=True, can_pp=False)
            )
            self.channels.append(ch)

    def construct_infrastructure(self, min_prio, max_prio, dependencies):
        # Make driver
        self.driver = ProtectionDomain("timer_driver", "timer_driver.elf", scheduling=SchedulingProperties(min_prio, passive=True))
        self.pds.append(self.driver)
        return min_prio


@subsystem_register_dependency(DummyClock)
class DummyI2C(Subsystem):
    def __init__(self):
        super().__init__("i2c")
        self.driver = None
        self.virt = None

    def connect_clients(self):
        assert self.driver is not None and self.virt is not None
        # Clients are connected with a channel allowing PPs and nothing else
        for c in self.clients:
            if c.priority >= self.virt.priority:
                raise SubsystemBuildError(f"Client {c} has a priority higher "
                                          f"than virt's ({self.virt.priority})!")
            # Make channel
            ch = Channel(
                    Channel.End(c, can_notify=False, can_pp=True),
                    Channel.End(self.virt, can_notify=True, can_pp=False)
            )
            self.channels.append(ch)

    def construct_infrastructure(self, min_prio, max_prio, dependencies):
        # Make driver
        self.driver = ProtectionDomain("i2c_driver", "i2c_driver.elf", scheduling=SchedulingProperties(min_prio + 1))
        self.virt = ProtectionDomain("i2c_virt", "i2c_virt.elf", scheduling=SchedulingProperties(min_prio))
        d_v_ch = Channel(
                    Channel.End(self.virt, can_notify=True, can_pp=False),
                    Channel.End(self.driver, can_notify=True, can_pp=False)
        )
        self.channels.append(d_v_ch)
        self.pds.extend([self.driver, self.virt])
        # Connect driver to clock
        dependencies[DummyClock].add_client(self.driver)
        return min_prio + 1


@subsystem_register_dependency(DummyTimer)
@subsystem_register_dependency(DummyI2C)
class DummyPMIC(Subsystem):
    def __init__(self):
        super().__init__("pmic")

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

    def construct_infrastructure(self, min_prio, max_prio, dependencies):
        # Make driver
        self.driver = ProtectionDomain("pmic_driver", "pmic_driver.elf", scheduling=SchedulingProperties(min_prio))
        self.pds.extend([self.driver])
        # connect deps
        dependencies[DummyTimer].add_client(self.driver)
        dependencies[DummyI2C].add_client(self.driver)
        return min_prio


# Make system and subsystems
sdf = System(aarch64, 0x100000000)

i2c = DummyI2C()
pmic = DummyPMIC()
timer = DummyTimer()
clk = DummyClock()

# Client

client = ProtectionDomain("client", "client.elf", priority=1)
# Adding a client to the sdf is optional ... if it's a child of a subsystem
# it will be added when the subsystem is.
# sdf.add_pd(client)

i2c.add_client(client)
pmic.add_client(client)
timer.add_client(client)

# Do topological sort in isolation
top_sorted = dep_map.topological_sort()
print(top_sorted)

# Check top sort is sane
assert top_sorted.index(DummyPMIC) < top_sorted.index(DummyI2C)
assert top_sorted.index(DummyPMIC) < top_sorted.index(DummyTimer)
assert top_sorted.index(DummyI2C) < top_sorted.index(DummyClock)

# Build!
for s in [i2c, pmic, timer, clk]:
    sdf.add_subsystem(s)

sdf.resolve_subsystems()
for p in sdf.pds:
    print(p)

sdf.write_xml_file("dummysubsystems.system")
