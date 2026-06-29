# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from abc import ABC, abstractproperty, abstractmethod
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as et
from typing import Optional


class IOPort:
    """
    A representation of an x86 IOPort.
    """
    def __init__(self,
                 addr: int,
                 size: int,
                 id: Optional[int] = None):
        self.addr = addr
        self.size = size
        self.id = id


    def render(self, parent: et.Element):
        # ID should be set by PD when calling pd.add_ioport()
        if self.id is None:
            raise RuntimeError("ID must be set before rendering an ioport!")
        ioport = et.SubElement(parent, "ioport")
        ioport.set("id", str(self.id))
        ioport.set("addr", str(self.addr))
        ioport.set("size", str(self.size))
