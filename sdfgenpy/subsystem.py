# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Type, List
from abc import abstractmethod
from collections import defaultdict
from .pd import ProtectionDomain

class Subsystem:
    """
    A subsystem is a grouping of PDs, as well as channels,
    memory regions and maps between them. This class can be
    considered a factory that builds all of the elements of the
    subsystem and then inserts them into the System.

    At init, the subsystem is just a container to add clients to.

    NOTE: we are currently limited to only having one instance of
          a subsystem on the system. This can be added in the future,
          it will just require some more complex bookkeeping + a different
          API for declaring dependencies to allow resolution to find the
          "right" option out of the available subsystems. You can get
          around this as a hack by subclassing a subsystem to give it
          a new identifier for the resolver, letting you make copies.
    """
    def __init__(self, name: str, depends_on: List[Type] = [], clients_allowed: bool = True):
        self.name = name
        self.built = False  # "have we added all clients and connected them?"
        self.dependencies = depends_on
        self.clients: List[ProtectionDomain] = []
        self.pds: List[ProtectionDomain] = []
        self.channels: List[Channel] = []
        self.mrs: List[MemoryRegion] = []
        self.clients_allowed = clients_allowed

    @property
    def get_deps(self):
        return self.dependencies

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

    @abstractmethod
    def construct_infrastructure(self, min_prio: int, max_prio: int) -> int:
        """
        Set up the PDs that compose this subsystem; that is, anything that composes
        this subsystem and isn't a client. E.g. drivers and virtualisers for sDDF
        driver classes, networking components like the subsystem, etc.

        This method should attempt to assign priorities as close to the maximum as
        possible, and should return the smallest priority used so that any
        dependencies of this subsystem can be constructed correctly.

        Args:
            min_prio: int minimum priority that can be used
            max_prio: int maximum priority that can be used
        Returns:
            int: smallest priority used.
        """
        ...

    def build(self, max_priority: int) -> int:
        """
        Construct subsystem, initialising all PDs and connecting clients
        if possible.

        Args:
            max_priority: int -> max priority this class can assign to itself.

        Returns:
            int: minimum priority of this subsystem, used to ensure anything that depends
                 on this won't be of higher priority. Does NOT include client priorities.
        """
        # Minimum priority is the highest priority of a PD + 1.
        min_prio = max([x.priority for x in self.clients])+1 if self.clients_allowed else 0
        if min_prio >= max_priority:
            # If no clients, something has gone hideously wrong. Print an
            # explicit warning rather leaving a StopIteration.
            if not self.clients_allowed:
                raise RuntimeError(f"Impossible priority range! = [{min_pro}, {max_priority}]")

            problem_client = next(x for x in self.clients if x.priority == (min_prio-1))
            raise RuntimeError(
                f"Subsystem cannot be implemented! Minimum "
                f"priority of {min_prio-1} from client {problem_client} is > "
                f"{max_priority} defined by build constraints!")

        # Set up infrastructure
        min_prio_reserved = self.construct_infrastructure(min_prio, max_priority)

        # Connect clients if needed
        if self.clients_allowed:
            self.connect_clients()

        return min_prio_reserved


    @staticmethod
    def topological_sort(ssystems: List) -> List:
        """
        Topologically sort subsystem graph, returning a list of subsystems
        in the order that they should be be built. This method will ensure
        all subsystems are unique, but cannot check that priorities are
        correct, since they aren't assigned until building starts.

        This method will also check for cycles and raise an exception if they
        are encountered.

        Returns:
            List of topologically sorted subsystems
        """
        # Validate uniqueness of subsystems
        ss_types = [type(x) for x in ssystems]
        duplicates = []

        # Iterate to find duplicates explicitly for helpful error
        for t in ss_types:
            if ss_types.count(t) != 1:
                duplicates.append(t)
        if len(duplicates) != 0:
            raise RuntimeError(f"Subsystem list contains duplicates! -> {duplicates}")

        # No duplicates - we can handle this
        # Build dictionary of Subsystem->[deps] for fast traversal.
        g = defaultdict(list)
        for s in ssystems:
            g[s] = s.get_deps

        # This graph has the following possible properties:
        # a. May be cyclic. Must error if so.
        # b. Is directed.
        # c. May have disconnected components.

        # Perform topological sort and cycle check at the same time by finding entry and exit times
        g_times = defaultdict(lambda: [-1, -1]) # (entry, exit)
        top_lst = []
        for v_i in g.keys():
            if g_times[v_i][0] != -1:
                # Already checked, skip.
                continue

            dfs_time = 0
            def dfs(v):
                # Set entry time
                nonlocal dfs_time
                dfs_time += 1
                g_times[v][0] = dfs_time

                # Search neighbours
                for neighbour in g[v]:
                    # If unvisited
                    if g_times[neighbour][0] == -1:
                        dfs(neighbour)
                    elif g_times[neighbour][0] != -1 and g_times[neighbour][1] == -1:
                        # Cycle! We went through this node before but haven't returned
                        # from that call.
                        raise RuntimeError(f"Circular dependency found @ "
                                           f"{neighbour}!")
                # Set our exit time
                dfs_time += 1
                g_times[v][1] = dfs_time
                top_lst.append(v)
            dfs(v_i)

        return top_lst
