# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import List, ClassVar, Optional, Union, Type, Dict
from abc import abstractmethod, abstractclassmethod, ABC
from collections import defaultdict, deque

from .pd import ProtectionDomain
from .configstruct import ConfigStruct
from .memory import MemoryRegion


class SubsystemBuildError(RuntimeError): ...


class Subsystem(ABC):
    """
    A subsystem is a grouping of PDs, as well as channels,
    memory regions and maps between them. This class can be
    considered a factory that builds all of the elements of the
    subsystem and then inserts them into the System.

    At init, the subsystem is just a container to add clients to.
    """

    def __init__(self, name: str, clients_allowed: bool = True):
        if type(self) == Subsystem:
            raise TypeError("Cannot instantiate abstract base class!")
        self.name = name
        self.built = False  # "have we added all clients and connected them?"
        self.clients: List[ProtectionDomain] = []
        self.pds: List[ProtectionDomain] = []
        self.channels: List["Channel"] = []
        self.mrs: List[MemoryRegion] = []
        self.clients_allowed = clients_allowed

    def add_client(self, client: ProtectionDomain):
        """
        Add a client to the subsystem list, but do nothing else just yet.

        This method may be overloaded by some classes to add extra parameters to clients,
        e.g. assigning MAC addresses for networking or I2C addresses for I2C.
        """
        if not self.clients_allowed:
            raise RuntimeError(f"{self} does not allow clients!")
        if client not in self.clients:
            self.clients.append(client)

    def add_internal_pd(self, pd: ProtectionDomain):
        """
        Add a non-client PD, e.g. drivers, virtualisers, PDs as a part of an application.
        This should be used on PDs which do not require any connection as clients.
        """
        if pd not in self.pds:
            self.pds.append(pd)

    def add_mr(self, mr: MemoryRegion):
        """
        Add a memory region used by this subsystem to the list of MRs to hand off
        to render in System.
        """
        if mr not in self.mrs:
            self.mrs.append(mr)

    def add_channel(self, channel: "Channel"):
        """
        Add a channel used by this subsystem to the list of channels to hand off
        to render in System.
        """
        if channel not in self.channels:
            self.channels.append(channel)

    def get_pds(self):
        """
        Get all non-client PDs.
        """
        if self.built:
            return self.pds
        raise RuntimeError("Cannot get PDs from an unbuilt subsystem!")

    def get_clients(self):
        """
        Get all non-client PDs.
        """
        return self.clients

    def get_mrs(self):
        if self.built:
            return self.mrs
        raise RuntimeError("Cannot get mrs from an unbuilt subsystem!")

    def get_channels(self):
        if self.built:
            return self.channels
        raise RuntimeError("Cannot get channels from an unbuilt subsystem!")

    def connect_clients(self):
        """
        Attempt to connect clients to the PDs that compose this subsystem.

        This method shouldn't need to be called directly, Subsystem.build() automates this.
        """
        ...

    def generate_config_structs(self) -> List[ConfigStruct]:
        """
        Generate any config structs this subsystem requires and return
        them as a list. Subsystems that utilise them should override
        this parent method. This method is not abstract to allow classes
        with no config structs to ignore this.
        """
        return []

    def build(self):
        """
        Construct subsystem, initialising all PDs and connecting clients
        if possible.
        """
        if self.built:
            raise RuntimeError("Cannot build a subsystem more than once!")

        # Connect clients if needed
        if self.clients_allowed:
            self.connect_clients()
        self.built = True
