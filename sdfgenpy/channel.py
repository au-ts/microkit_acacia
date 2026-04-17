# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from typing import Optional, Tuple
from dataclasses import dataclass
import xml.etree.ElementTree as et
from abc import ABC, abstractproperty
from .pd import ProtectionDomain

class Channel:
    @dataclass(frozen=True)
    class End:
        pd: ProtectionDomain
        ch_id: int
        can_notify: bool
        can_pp: bool
        def __post_init(self):
            if ch_id < 0 or ch_id > 255:
                raise ValueError(f"Invalid channel id {ch_id}!")

    def __init__(
                 self,
                 end_a: End,
                 end_b: End
                 ):
        self.end_a = end_a
        self.end_b = end_b

        # Enforce that PPCs only go to higher priorities
        for pp_caller, pp_receiver in [(end_a, end_b), (end_b, end_a)]:
            if not pp_caller.can_pp:
                continue
            if pp_caller.pd.priority >= pp_receiver.pd.priority:
                raise RuntimeError("PPCs can only go from low to high priorty!")

    def render(self, system_root: et.Element):
        channel = et.SubElement(system_root, "channel")
        for end in [end_a, end_b]:
            end = et.SubElement(channel, "end")
            end.set("pd", end.pd.name)
            end.set("id", end.ch_id)
            # We only set notify if it's false for some reason
            if not end.can_notify:
                end.set("notify", "false")
            # We only set pp if it's true for some reason
            if not end.can_pp:
                end.set("pp", "true")

            # note: "some reason" defined by microkit, not us.
        return channel


