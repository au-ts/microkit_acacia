# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import xml.etree.ElementTree as et  # type: ignore
from dataclasses import dataclass
from typing import Optional

from .pd import ProtectionDomain
from .system import AcaciaSystemError, System


class Channel:
    """
    Acacia representation of a Microkit Channel object.
    https://docs.sel4.systems/projects/microkit/manual/latest/#channels

    Initialising an instance of this class will register a channel with Acacia, causing
    it to be created when rendering the XML.

    Channels have two `Ends` representing the `ProtectionDomain`s on either side.

    Acacia will prevent you from creating channels that either have no effect or are invalid
    (e.g. if PPCs go from a high priority -> low priority, not allowed in Microkit).

    Channel ends will automatically be assigned channel IDs from the pool of IRQ/Channel IDs
    available for each PD at `__init__()`.
    * In almost all cases, you should allow these to be automatically assigned.
    * **WARNING**: manual assignment currently will conflict with automatic assignment.
                   E.g. an automatically created channel can take ID=0, preventing a manual
                   assignment of ID=0. We may defer automatic assignment to Acacia build time
                   (as is the case with MR paddrs) in the future.
    """
    @dataclass
    class End:
        """
        One of the two ends of a channel where a ProtectionDomain interacts with it.
        By default:
        * `Ends` allow notifications
        * `Ends` prohibit protected procedure calls.

        You may optionally specify the channel ID of the end, although it will be automatically
        assigned when handed to a `Channel` if you do not.

        If using this class in a subsystem build hook, you should NEVER manually assign IDs.
        """
        pd: ProtectionDomain
        can_notify: bool = True
        can_pp: bool = False
        ch_id: Optional[int] = None

        def __post_init__(self):
            if self.ch_id is not None and (self.ch_id < 0 or self.ch_id >= 255):
                raise ValueError(f"Invalid channel id {self.ch_id}!")

        def __repr__(self) -> str:
            perms = (
                f"pp={self.can_pp}, notify={self.can_notify}, "
                f"id={'unassigned' if self.ch_id is None else self.ch_id}"
            )
            return f"<Channel.End for PD={self.pd.name} w/ {perms}>"

    def __init__(self, sdf: System, end_a: End, end_b: End):
        # Sanity: check that system is not final. We don't allow allocation of any type
        #         once the system is assembled, or we risk failing to include things in
        #         the XML!
        if not sdf.microkit_alloc_allowed:
            raise AcaciaSystemError("System is finalised, cannot add Microkit objects!")

        self.end_a = end_a
        self.end_b = end_b
        self.sdf = sdf

        # Enforce that PPCs only go to higher priorities
        for pp_caller, pp_receiver in [(end_a, end_b), (end_b, end_a)]:
            if not pp_caller.can_pp:
                continue
            if pp_caller.pd.priority >= pp_receiver.pd.priority:
                raise RuntimeError(
                    f"PPC from {pp_caller} to {pp_receiver} cannot have "
                    f"descending priorities!"
                )

        # Make sure channel does something
        if (
            not end_a.can_notify
            and not end_b.can_notify
            and not end_a.can_pp
            and not end_b.can_pp
        ):
            raise RuntimeWarning("Channel has no effect! Neither end can PP or notify!")

        # Allocate channel IDs
        for end in [end_a, end_b]:
            end.ch_id = end.pd.allocate_id(end.ch_id)

        # Allocate ourself to SDF
        self.sdf._add_channel(self)

    def render(self, system_root: et.Element):
        """
        Return the Microkit XML representing this element. This is called automatically
        by Acacia and should not need to be manually called under normal circumstances.
        """
        channel = et.SubElement(system_root, "channel")
        for e in [self.end_a, self.end_b]:
            end = et.SubElement(channel, "end")
            end.set("pd", e.pd.name)
            end.set("id", str(e.ch_id))
            # Only set notify and pp if it changes the meaning from
            # microkit's default mode.
            if not e.can_notify:
                end.set("notify", "false")
            if e.can_pp:
                end.set("pp", "true")

        return channel

    def id_for_pd(self, end_pd) -> Optional[int]:
        """
        Return the channel ID for this channel for the given PD.
        I.e. the channel number `ch` which `end_pd` can `microkit_notify()"-ed to send
        a notification to the other end of the channel.

        This is a convenience function to make config serialisation less ambiguous.
        We can also avoid programming errors related to remembering end_a vs. end_b
        this way.
        """
        if self.end_a.pd is end_pd:
            return self.end_a.ch_id
        if self.end_b.pd is end_pd:
            return self.end_b.ch_id
        raise RuntimeError(f"PD {end_pd} isn't in this channel!")

    def __repr__(self) -> str:
        return f"<Channel with ends a={self.end_a} b={self.end_b}>"
