# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
from .pd import ProtectionDomain
from .ipc import Channel

class Connection:
    """
    A connection encapsulates IPC connections, memory mappings
    and other PD-to-PD connections. This is a convenience structure
    to minimise room for error when defining complex subsystems.
    """
    def __init__(self, pd_a: ProtectionDomain, pd_b: ProtectionDomain):
        for pd in [pd_a, pd_b]:
            if not isinstance(pd, ProtectionDomain):
                raise TypeError(f"{pd} is not a ProtectionDomain!")
        self.pd_a = pd_a
        self.pd_b = pd_b
        self.channels: List[Channel] = []



