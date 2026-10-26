# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from __future__ import annotations
from abc import ABC
from typing import TYPE_CHECKING
import xml.etree.ElementTree as et

if TYPE_CHECKING:
    from .pd import ProtectionDomain


class CapMap(ABC):
    """
    Representation of the Microkit's capability mapping feature.
    See https://github.com/seL4/microkit/blob/main/docs/manual.md#cspace-sdf-cspace for more details
    """

    tag: str
    attr: str

    def __init__(self, slot: int, obj):
        if type(self) is CapMap or type(self) is PDCapMap:
            raise TypeError("Cannot instantiate abstract base class!")
        if slot < 1:
            raise ValueError("Slot must be greater than 0")
        self.slot = slot
        self.obj = obj

    def render(self, parent: et.Element):
        # PDCapMap can't be used directly
        assert self.tag is not None

        entity = et.SubElement(parent, self.tag)
        entity.set("slot", str(self.slot))
        entity.set(self.attr, str(self.obj.name))


class PDCapMap(CapMap):
    attr = "pd"


class TCBCapMap(PDCapMap):
    tag = "cap_tcb"


class SchedCxtCapMap(PDCapMap):
    tag = "cap_sc"


class VSpaceCapMap(PDCapMap):
    tag = "cap_vspace"


class MicrokitCSpace:
    """Representation of the Microkit CSpace"""

    def __init__(self):
        self.slot_to_cap_map: dict[int, CapMap] = {}

    def add_cap_map(self, cap_map: CapMap):
        if cap_map.slot in self.slot_to_cap_map:
            raise ValueError(f"Slot {cap_map.slot} already occupied")

        self.slot_to_cap_map[cap_map.slot] = cap_map

    def render(self, parent: et.Element):
        if len(self.slot_to_cap_map) > 0:
            cspace = et.SubElement(parent, "cspace")
            for cap in sorted(self.slot_to_cap_map.values(), key=lambda cap: cap.slot):
                cap.render(cspace)
