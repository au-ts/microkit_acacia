# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import xml.etree.ElementTree as et
from typing import Optional


class IOPort:
    """
        A representation of an x86 IOPort.

        This object is a thin wrapper around the Microkit object.

    Similarly to IRQs and channel end IDs, an explicit ID may be optionally
        given when constructing this class. If it is not given, it will be automatically
        assigned when adding it to a ProtectionDomain.

        If using this class in a subsystem build hook, you should NEVER manually assign IDs.

        Note: it is possible for explicitly assigned IDs to clash (possibly with automatically
              -generated ones!). In almost all cases, you should use automatic allocation.
    """

    def __init__(self, addr: int, size: int, id: Optional[int] = None):
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

    def __repr__(self) -> str:
        return f"<IOPort#{self.id} @ {self.addr} of size {self.size}>"
