# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import List, ClassVar, Optional, Union, Type, Dict
from abc import abstractmethod, abstractclassmethod, ABC
from collections import defaultdict, deque
from .pd import ProtectionDomain
from .configstruct import ConfigStruct

class Subsystem(ABC):
    """
    A subsystem is a grouping of PDs, as well as channels,
    memory regions and maps between them. This class can be
    considered a factory that builds all of the elements of the
    subsystem and then inserts them into the System.

    At init, the subsystem is just a container to add clients to.
    """
    def __init__(self, name: str, clients_allowed: bool = True, forced_prio: Optional[int] = None):
        self.name = name
        self.built = False  # "have we added all clients and connected them?"
        self.clients: List[ProtectionDomain] = []
        self.pds: List[ProtectionDomain] = []
        self.channels: List[Channel] = []
        self.mrs: List[MemoryRegion] = []
        self.clients_allowed = clients_allowed

    def add_client(self, client: ProtectionDomain):
        """
        Add a client to the subsystem list, but do nothing else just yet.

        This method may be overloaded by some classes to add extra parameters to clients,
        e.g. assigning MAC addresses for networking or I2C addresses for I2C.
        """
        if not self.clients_allowed:
            raise RuntimeError(f"{self.__repr__} does not allow clients!")
        if client not in self.clients:
            self.clients.append(client)

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

    @abstractmethod
    def connect_clients(self):
        """
        Attempt to connect clients to the PDs that compose this subsystem. This should be
        called after `construct_infrastructure()`.

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

    def build(self) -> int:
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
