# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import List, ClassVar, Optional, Union, Type, Dict
from abc import abstractmethod, abstractclassmethod, ABC
from collections import defaultdict, deque
from dataclasses import dataclass
from functools import wraps
from .pd import ProtectionDomain
from .util import parameterised_decorator


class DependencyDefinitionError(Exception): ...


class __DependencyMap:
    """
    This class acts as a single source of truth for tracking
    dependencies between subclasses.

    Never make your own instance of this class! Use the one
    exposed by `subsystem.get_dependencies()`. I was going to make
    this a singleton class but apparently that's considered an anti
    -pattern, and we instead trust users to use the module-level
    interface.

    Use the decorators in this module to register dependencies.
    """
    def __init__(self):
        # Maps subsystem class type -> List[subsystem class types]
        self.dep_map = defaultdict(list)
        # A list of subsystems that want the max priority on the system.
        # This is used when topological sorting to order these PDs to the
        # end of the ordering AND by `System.resolve_subsystems` to implement
        # this constraint.
        self.max_prio_systems = []
        # Todo: also register modules to raise useful warnings when working
        # across modules. E.g. register sddf, and throw an error immediately
        # if a dependent module (e.g. firewall) tries to request an sddf dep.


    def register(self, ssystem: Type["Subsystem"], dep: Type["Subsystem"]):
        if ssystem in self.dep_map and dep in self.dep_map[ssystem]:
            raise DependencyDefinitionError(f"Cannot register the same subsystem {ssystem} more than once!")

        self.dep_map[ssystem].append(dep)

        if ssystem is dep:
            # sanity: no self-references!
            raise DependencyDefinitionError("Subsystems cannot have a dependency on themselves!")

        # Make sure dep also has an entry
        if dep not in self.dep_map:
            # This is a no-op, but ensures that the key is present and won't be
            # inserted in the middle of a DFS.
            self.dep_map[dep] = []
        else:
            # Check this isn't a direct circular dependency. We don't bother
            # to perform a full cycle check here, we do that when resolving.
            if ssystem in self.dep_map[dep]:
                raise DependencyDefinitionError(f"{ssystem}'s dependency {dep} depends "
                                                f"on {ssystem}! Circular dependency!")

    def add_max_prio_system(self, ssystem: Type["Subsystem"]):
        if ssystem not in self.dep_map:
            self.dep_map[ssystem] = []
        else:
            if len(self.dep_map[ssystem]) != 0:
                raise RuntimeError("Cannot be max priority if system depends "
                                   "on anything else!")

        if ssystem in self.max_prio_systems:
            raise DependencyDefinitionError("Cannot define max prio multiple times!")
        self.max_prio_systems.append(ssystem)

    def topological_sort(self, filter=None) -> List:
        """
        Topologically sort subsystem graph, returning a list of subsystems
        in the order that they should be be built. This method will ensure
        all subsystems are unique, but cannot check that priorities are
        correct, since they aren't assigned until building starts.

        This method will also check for cycles and raise an exception if they
        are encountered.

        Args:
            filter: List[Type[Subsystem]]: only include these subsystems
            and their deps.

        Returns:
            List of topologically sorted subsystem dependencies.
        """

        # This graph has the following possible properties:
        # a. May be cyclic. Must error if so.
        # b. Is directed.
        # c. May have disconnected components.

        # Perform topological sort and cycle check at the same time by finding entry and exit times
        g_times = defaultdict(lambda: [-1, -1]) # (entry, exit)
        top_lst = []
        if filter is None:
            ss_in = self.keys()
        else:
            ss_in = filter
        for v_i in ss_in:
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
                for neighbour in self.dep_map[v]:
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

        # reverse list - DFS output is inverse topological sort
        top_lst = top_lst[::-1]

        # Reorder list for any systems that require max priority. Invariant:
        # these all have no dependencies on other systems, and are safe to move
        # as a result. These will probably be in the correct position anyway,
        # but it is possible that non-max constrained systems will appear ahead
        # of them, so we must do this.
        # TODO: make this more efficient. This may chug on very large graphs as removal
        # is an O(n) operation on lists as it must first linearly search and then re-shuffle
        # the list after.
        for s in self.max_prio_systems:
            if s in top_lst:
                top_lst.remove(s)
            top_lst.append(s)

        return top_lst

    def keys(self):
        return self.dep_map.keys()

    def values(self):
        return self.dep_map.values()

    def __repr__(self):
        return str(self.dep_map)

    def clear(self):
        print("Warning: dependency map explicitly cleared!")
        return self.dep_map.clear()


# Single dependency map for all of sdfgen
sdfgen_depmap = __DependencyMap()


def get_dependency_map():
    return sdfgen_depmap


@parameterised_decorator
def subsystem_register_dependency(ss_class, dep):
    """
    Decorator to register a (direct) dependency of a subsystem.
    A direct dependency is another subsystem this subsystem must
    be a client of.

    You don't need to define dependencies of your dependencies. They do
    that themselves! Only worry about what your subsystem needs to talk
    to.
    """
    # print(f"{ss_class} depends on {dep}")
    if not issubclass(ss_class, Subsystem):
        raise TypeError("Only subclasses of sdfgen.subsystem.Subsystem are "
                        "valid dependencies!")

    get_dependency_map().register(ss_class, dep)
    return ss_class

def forced_max_priority(ss_class):
    """
    Denote that this subsystem must have max to be constructed.
    This is principally intended to allow timer devices in the sDDF to claim
    the highest priority on the system.

    This will be used by the topological sorter to ensure that this class is
    placed at the very top of the dependeny list.
    """
    if not issubclass(ss_class, Subsystem):
        raise TypeError("This decorator only operates on subsystem classes")

    get_dependency_map().add_max_prio_system(ss_class)
    setattr(ss_class, "force_max_prio", True)
    return ss_class


class Subsystem(ABC):
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
    def __init__(self, name: str, clients_allowed: bool = True, forced_prio: Optional[int] = None):
        self.name = name
        self.built = False  # "have we added all clients and connected them?"
        self.clients: List[ProtectionDomain] = []
        self.pds: List[ProtectionDomain] = []
        self.channels: List[Channel] = []
        self.mrs: List[MemoryRegion] = []
        self.clients_allowed = clients_allowed
        self.forced_prio = forced_prio  # For subsystems with a forced priority. E.g. timer

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

    @abstractmethod
    def construct_infrastructure(self, min_prio: int, max_prio: int, dependencies: Dict[Type["Subsystem"], "Subsystem"]=None) -> int:
        """
        Set up the PDs that compose this subsystem; that is, anything that composes
        this subsystem and isn't a client. E.g. drivers and virtualisers for sDDF
        driver classes, networking components like the subsystem, etc.

        This method should attempt to assign priorities as close to the MINIMUM as
        possible, and should return the largest priority used so that any
        dependencies of this subsystem can be constructed correctly.

        Args:
            min_prio: int minimum priority that can be used
            max_prio: int maximum priority that can be used
            dependencies: Dict[SubsystemType, Subsystem] -> dictionary of dependencies
                          to connect with infrastructure.
        Returns:
            int: largest priority used.
        """
        ...

    def build(self, min_priority: int, dependencies: Dict[Type["Subsystem"], "Subsystem"]) -> int:
        """
        Construct subsystem, initialising all PDs and connecting clients
        if possible.

        Args:
            max_priority: int -> max priority this class can assign to itself.
            dependencies: Dict[SubsystemType, Subsystem] -> dictionary of dependencies for easy
                          indexing by type. Used by construct_infrastructure as described in its
                          docstring.

        Returns:
            int: minimum priority of this subsystem, used to ensure anything that depends
                 on this won't be of higher priority. Does NOT include client priorities.
        """
        if self.built:
            raise RuntimeError("Cannot build a subsystem more than once!")

        # Minimum priority is the highest priority of a PD + 1.
        min_c_prio = max([x.priority for x in self.clients])+1 if self.clients_allowed and len(self.clients) > 0 else 0

        # if min_c_prio > min_priority:
        #     # If no clients, something has gone hideously wrong. Print an
        #     # explicit warning rather leaving a StopIteration.
        #     if not self.clients_allowed:
        #         raise RuntimeError(f"Impossible priority range! = [{min_c_prio}, {min_priority}]")
        #
        #     problem_client = next(x for x in self.clients if x.priority == (min_c_prio-1))
        #     raise RuntimeError(
        #         f"Subsystem cannot be implemented! Minimum "
        #         f"priority of {min_c_prio-1} from client {problem_client} is > "
        #         f"{min_priority} defined by build constraints!")
        #
        # Set up infrastructure
        min_ss_prio = max(min_c_prio, min_priority)
        print(min_priority)
        min_prio_reserved = self.construct_infrastructure(min_ss_prio, 255, dependencies=dependencies)

        # Sanity: min prio used > min prio. This should also catch NoneType
        # errors for subsystems that are incorrectly defined and do not return
        # a minimum priority as expected.
        if min_prio_reserved < min_priority:
            raise RuntimeError(f"Reserved prio {min_prio_reserved} < min {min_priority}!")

        # Connect clients if needed
        if self.clients_allowed:
            self.connect_clients()
        self.built = True
        return min_prio_reserved
