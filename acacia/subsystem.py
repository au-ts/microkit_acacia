# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, Callable, ClassVar, List, TypeVar

# To avoid circular imports, we only do a "real" import when type checking.
if TYPE_CHECKING:
    from acacia.configstruct import ConfigStruct
    from acacia.pd import ProtectionDomain

    from .system import System


_BUILD_HOOK_MARKER = "__acacia_build_hook__"
_BuildHookMethod = TypeVar(
    "_BuildHookMethod",
    bound=Callable[..., None],
)


class SubsystemBuildError(RuntimeError):
    """
    Something caused a subsystem to fail to assemble itself.
    """


class Subsystem(ABC):
    """
    A subsystem is a grouping of PDs, as well as channels,
    memory regions and maps between them. It is the primary abstraction
    Acacia offers to modularise Microkit applications and modules.

    If a subsystem allows clients, these are ProtectionDomains using the services
    supplied by the subsystem (by default - this can be overridden if needed).

    This class is designed to be used exclusively by subclassing it to define your module.

    **We strongly recommend reading the Subsystem programming model guide in
    `./docs/subsystem_model.md` before writing your first module!**

    Subsystems offer three fundamental capabilities:
    1. A "client-server" style API, where subclasses implement the server logic
       in `__init__()` and clients PDs are added with `add_client()` (possibly overloaded
       if the client needs additional options).
    2. Infrastructure to "build" the subsystem by invoking some number of `build_hook`s.
       A build hook is a class method annotated with the `@build_hook` decorator, which is
       run when the top-level Acacia `System` decides to construct this class. Build hooks
       are run top-to-bottom in the file (or in MRO if inheriting them, i.e. parents run first).
    3. An encapsulation of `ConfigStructs` that describe the configuration of the server components
       and any data to tell clients how to interact with the server.

    Subsystems may have no clients if the superclass is instantiated with `allow_clients=False`.
    This allows representing arbitrary modules, or possibly modules that instrument some other
    subsystem, or maybe only a single client (see `sddf.acacia_sddf.ipstacks.py`).

    When a subsystem is built by Acacia:
        1. All build hooks are executed in top-to-bottom order within the class, or MRO for
           superclass methods.
        2. Config structs are generated afterwards by Acacia, by calling
           `generate_config_structs`.

    # WRITING A SUBSYSTEM

    Consider what your subsystem needs to do.

    Your `__init__()` should build anything that clients depend on as well as any dependencies for
    the whole subsystem (e.g. references to another subsystem this subsystem is a client to).
    E.g. for a driver subsystem, you should probably create your driver PD and associated
    virtualiser.

    ## Depending on other subsystems

    Per the Subsystem programming model, you should ALWAYS take references to other subsystems you
    depend on in `__init__()`. E.g. if you are writing an ethernet subsystem which needs to give
    the driver access to a timer subsystem, you should:
        a. Take the timer subsystem instance as an arg ... `__init__(self, timer ...)`;
        b. Create the driver PD in `__init__`;
        c. Add the driver as a client to the timer subsystem in `__init__`.

    You should never add clients to other subsystems in a build hook as this may lead to undefined
    behaviour!

    ## Why create infrastructure in `__init__`?

    You could technically do everything in a build hook, but it is useful to create PDs etc.
    early since this allows users to modify them in the metaprogram...
    E.g. changing which CPU core the driver runs on, adding the driver as a client to a different
    subsystem, etc.

    ## Dealing with clients

    Your `add_client()` method can remain as default in most cases, i.e. if you just need to
    specify "this PD is
    related to this subsystem". The easiest way to remember that some config belongs to clients
    is to create a
    dictionary called `client_configs: Dict[ProtectionDomain, Dict | dataclass]`, where you
    simply store the args
    from your overload in it.

    To deal with your clients, you will need to add at least one `build_hook` (conventionally
    named `connect_clients`).
    This should probably run AFTER any other build hooks (i.e. declared last) and should
    create channels, MRs, maps and
    and anything else needed for clients.

    ## Configuring PDs with ConfigStructs

    If you require `ConfigStructs`, you should declare a `generate_config_structs` method
    in your subclass. It should
    return a `List[ConfigStruct]`. You should probably create your ConfigStructs or keep
    the associated metadata somewhere
    in a class instance variable.

    ## If you do not want multiple clients

    ...you should instantiate your subclass with `super().__init__(sdf, name, allow_clients=False).

    You can then make your subsystem do whatever you'd like ... if you only need a single client,
    a useful pattern is to accept a reference to the client PD in `__init__()` - see `ipstacks.py`
    in the seL4 Device Driver Framework.

    ## Final words on dependencies

    **WARNING**: you should always add clients BEFORE any build hooks run! Subsystems are created
    in the order they are declared (i.e. when super().__init__() is called). This will mean that
    if the subsystem you depend on was created first, it will be built first, but you
    should not depend on this, as it is subject to change.

    We have a WIP dependency graph resolver that can ensure a correct build order, but it is not
    yet merged as it introduces a lot of complexity and it is not obvious that it is required for
    these cases.
    """

    def __init__(
        self,
        sdf: System,
        name: str,
        clients_allowed: bool = True,
    ) -> None:
        if type(self) is Subsystem:
            raise TypeError("Cannot instantiate abstract base class!")
        self.name = name
        self.built = False
        self.clients: List["ProtectionDomain"] = []
        self.clients_allowed = clients_allowed
        self.sdf = sdf
        self.build_hooks: List[Callable[[], None]] = []

        # getattr() converts each class function into a method bound to this
        # particular instance.
        for hook_name in type(self)._decorated_build_hook_names:
            self._add_build_hook(getattr(self, hook_name))

        # Register ourselves with SDF after initialization.
        self.sdf._add_subsystem(self)

    def add_client(self, client: "ProtectionDomain") -> None:
        """
        Add a client to the subsystem list, but do nothing else just yet.

        This method may be overloaded by some classes to add extra parameters
        to clients, e.g. assigning MAC addresses for networking or I2C
        addresses for I2C.
        """
        if not self.clients_allowed:
            raise RuntimeError(f"{self} does not allow clients!")

        if self.built:
            raise SubsystemBuildError(
                "Cannot add clients to a subsystem after it has been built!"
            )

        if client not in self.clients:
            self.clients.append(client)

    def get_clients(self) -> List["ProtectionDomain"]:
        """Get all client PDs."""
        return self.clients

    def generate_config_structs(self) -> List["ConfigStruct"]:
        """
        Generate any config structs this subsystem requires and return
        them as a list.

        Subsystems that use config structs should override this method. It is
        not abstract so subclasses without config structs can ignore it.
        """
        return []

    def build(self) -> None:
        """
        Run the subsystem's build hooks. This can only occur once per subsystem.

        This is automatically called when invoking a terminal action in Acacia,
        i.e. generating Microkit XML or config structs.
        """
        if self.built:
            raise RuntimeError("Cannot build a subsystem more than once!")

        for hook in self.build_hooks:
            try:
                hook()
            except Exception as e:
                raise SubsystemBuildError(
                    f"{self} failed to run build hook '{hook.__name__}'!"
                ) from e

        self.built = True

    def _add_build_hook(self, func: Callable[[], None]) -> None:
        """
        Add a function to call at build time for this subsystem. You probably
        shouldn't call this directly and should rather use the decorator.

        Hooks are executed in the order they are written. I.e.

        @build_hook
        def first_hook_to_run(self): ...

        @build_hook
        def second_hook_to_run(self): ...

        Hooks should have no arguments except `self`.
        """
        if not callable(func):
            raise TypeError(f"{func} is not callable!")

        if func in self.build_hooks:
            raise RuntimeWarning(f"{func} is already a build hook!")

        self.build_hooks.append(func)

    _decorated_build_hook_names: ClassVar[tuple[str, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """
        Set up build hooks, handling the possibility of a parent class defining some.
        """
        super().__init_subclass__(**kwargs)
        hook_names: List[str] = []

        # Add all parent class hooks first, if they exist. Ensures that they
        # run in inheritance order.
        for base in cls.__bases__:
            for name in getattr(base, "_decorated_build_hook_names", ()):
                if name not in hook_names:
                    hook_names.append(name)

        for name, member in cls.__dict__.items():
            # Check if this is already in our hook names dir - i.e. this is an override
            # of an inherited hook. If it's overridden, we implicitly lose the decorator,
            # unless it's explicitly added back.

            is_removed = False
            if name in hook_names:
                is_removed = True
                hook_names.remove(name)

            # ... add back if it was decorated again
            if _is_build_hook(member):
                hook_names.append(name)
                if is_removed:
                    # This will probably never be seen :)
                    print(
                        f"WARNING: build hook {member} of {cls} was overridden and re-marked as a build hook."
                        " It will now run in the order it appears where overridden, not with parent class!"
                    )

        # Edge case: multiple inheritance. If a method appears in multiple parents we want only the left-most
        #
        # E.g. class Child(UnhookedParent, HookedParent) -> UnhookedParent's method is inherited, but would
        # also become falsely marked as a buildhook since we see it from HookedParent in the base hook loop.
        # This filtering operation makes sure that the method that was actually inherited (not just any in
        # the base) is kept as a hook, since we will see the tag from the right class.
        cls._decorated_build_hook_names = tuple(
            name for name in hook_names if _resolved_member_is_build_hook(cls, name)
        )

    def __repr__(self) -> str:
        return f"<Subsystem({self.name} @ {id(self)})>"


def build_hook(method: _BuildHookMethod) -> _BuildHookMethod:
    """
    Mark a Subsystem instance method to be called during build().
    Hooks are run top-to-bottom in their class and should have no arguments except possibly `self`.

    If inheriting, all parent hooks run before the child's hooks.
    """
    setattr(method, _BUILD_HOOK_MARKER, True)
    return method


def _is_build_hook(member: object) -> bool:
    return bool(getattr(member, _BUILD_HOOK_MARKER, False))


def _resolved_member_is_build_hook(cls: type, name: str) -> bool:
    """
    Return whether the attribute selected by the class's MRO (method resolution order)
    is a build hook.
    """
    for owner in cls.__mro__:
        if name in owner.__dict__:
            return _is_build_hook(owner.__dict__[name])

    return False
