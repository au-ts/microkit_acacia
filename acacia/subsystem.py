# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Callable, List

# To avoid circular imports, we only do a "real" import when type checking.
if TYPE_CHECKING:
    from acacia.configstruct import ConfigStruct
    from acacia.pd import ProtectionDomain

    from .system import System


class SubsystemBuildError(RuntimeError): ...


class Subsystem(ABC):
    """
    A subsystem is a grouping of PDs, as well as channels,
    memory regions and maps between them. This class can be
    considered a factory that builds all of the elements of the
    subsystem and then inserts them into the System.

    At init, the subsystem is just a container to add clients to.
    """

    def __init__(self, sdf: System, name: str, clients_allowed: bool = True):
        if type(self) == Subsystem:
            raise TypeError("Cannot instantiate abstract base class!")
        self.name = name
        self.built = False  # "have we added all clients and connected them?"
        self.clients: List["ProtectionDomain"] = []
        self.clients_allowed = clients_allowed
        self.sdf = sdf
        # Register ourselves with SDF
        self.sdf._add_subsystem(self)
        self.build_hooks: List[Callable] = []

        # Sanity: throw an exception to warn users if they have used `connect_clients` when
        # it would have no effect.
        if "connect_clients" in type(self).__dict__ and not self.clients_allowed:
            raise SubsystemBuildError(
                f"{self.name} has defined connect_clients but has disabled "
                "clients! Use post_build_actions instead if you need to do something post-build."
            )
        elif clients_allowed:
            # Add connect clients.
            self.add_build_hook(self.connect_clients)

    def add_client(self, client: "ProtectionDomain"):
        """
        Add a client to the subsystem list, but do nothing else just yet.

        This method may be overloaded by some classes to add extra parameters to clients,
        e.g. assigning MAC addresses for networking or I2C addresses for I2C.
        """
        if not self.clients_allowed:
            raise RuntimeError(f"{self} does not allow clients!")
        if client not in self.clients:
            self.clients.append(client)

    def get_clients(self):
        """
        Get all non-client PDs.
        """
        return self.clients

    def connect_clients(self):
        """
        Attempt to connect clients to the PDs that compose this subsystem.
        If the subsystem has `clients_allowed=False`, this method will not be called.

        This method shouldn't need to be called directly, Subsystem.build() automates this.

        NOTE: this is exposed as a convenience, it is just added as a build hook.
        """
        ...

    def add_build_hook(self, func: Callable):
        """
        Add a function to call at build time for this subsystem. This can be used to perform
        arbitrary work after the user is finished customising the system such as adding automatic
        mapppings without risking conflict with manually specified items.

        Functions are called with no arguments - i.e. `func()`. Use lambdas to enclose scope if needed.
        NOTE: if you add a class method e.g. `add_build_hook(self.connect_clients())` it will still get
        a handle to `self`, i.e. it is run as `self.connect_clients(self)`.
        """
        if not callable(func):
            raise TypeError(f"{func} is not callable!")

        if func in self.build_hooks:
            raise RuntimeWarning(f"{func} is already a build hook!")

        self.build_hooks.append(func)

    def generate_config_structs(self) -> List["ConfigStruct"]:
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

        # Call post_build_hooks
        for f in self.build_hooks:
            f()

        self.built = True

    def __repr__(self) -> str:
        return f"<Subsystem({self.name} @ {id(self)}>"
