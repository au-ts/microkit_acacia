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


class SubsystemBuildError(RuntimeError): ...


class Subsystem(ABC):
    """
    A subsystem is a grouping of PDs, as well as channels,
    memory regions and maps between them. This class can be
    considered a factory that builds all of the elements of the
    subsystem and then inserts them into the System.

    At init, the subsystem is just a container to add clients to.
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
        """Run the subsystem's build hooks."""
        if self.built:
            raise RuntimeError("Cannot build a subsystem more than once!")

        for hook in self.build_hooks:
            hook()

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
