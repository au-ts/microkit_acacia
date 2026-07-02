# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Tuple
from dataclasses import dataclass
import xml.etree.ElementTree as et
from abc import ABC, abstractproperty
from .pd import ProtectionDomain


class Channel:
    @dataclass
    class End:
        pd: ProtectionDomain
        can_notify: bool
        can_pp: bool
        ch_id: Optional[int] = None

        def __post_init__(self):
            if self.ch_id is not None and (self.ch_id < 0 or self.ch_id >= 255):
                raise ValueError(f"Invalid channel id {self.ch_id}!")

    def __init__(self, end_a: End, end_b: End):
        self.end_a = end_a
        self.end_b = end_b

        # Enforce that PPCs only go to higher priorities
        for pp_caller, pp_receiver in [(end_a, end_b), (end_b, end_a)]:
            if not pp_caller.can_pp:
                continue
            if pp_caller.pd.priority >= pp_receiver.pd.priority:
                raise RuntimeError(
                    f"PPC from {pp_caller} to {pp_receiver} cannot have "
                    f"descending priorities!"
                )

        # Allocate channel IDs
        for end in [end_a, end_b]:
            end.ch_id = end.pd.allocate_id(end.ch_id)

    def render(self, system_root: et.Element):
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

    def id_for_pd(self, end_pd) -> int:
        """
        Return the channel ID for this channel for the given PD.
        This is a convenience function to make config serialisation less ambiguous.
        We can also avoid programming errors related to remembering end_a vs. end_b
        this way.
        """
        if self.end_a.pd is end_pd:
            return self.end_a.ch_id
        if self.end_b.pd is end_pd:
            return self.end_b.ch_id
        raise RuntimeError(f"PD {end_pd} isn't in this channel!")
