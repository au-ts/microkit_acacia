# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import xml.etree.ElementTree as et

import pytest

from acacia.arch import aarch64
from acacia.cspace import (
    TCBCapMap,
    SchedCxtCapMap,
    VSpaceCapMap,
)
from acacia.pd import ProtectionDomain
from acacia.system import System


@pytest.fixture
def sdf():
    """A stand-in System for entity constructors."""
    return System(aarch64, paddr_top=0x10000000)


class TestCapMap:
    def test_tcb_cap_map_dup_slot(self, sdf):
        pd_a = ProtectionDomain(sdf, "test_a", "test_a.elf", priority=100)
        pd_b = ProtectionDomain(sdf, "test_b", "test_b.elf", priority=100)
        pd_c = ProtectionDomain(sdf, "test_c", "test_c.elf", priority=100)

        pd_a.add_cap_map(TCBCapMap(1, pd_b))
        with pytest.raises(ValueError, match="Slot 1 already occupied"):
            pd_a.add_cap_map(TCBCapMap(1, pd_c))

    def test_tcb_cap_map(self, sdf):
        pd_a = ProtectionDomain(sdf, "test_a", "test_a.elf", priority=100)
        pd_b = ProtectionDomain(sdf, "test_b", "test_b.elf", priority=100)

        pd_a.add_cap_map(TCBCapMap(1, pd_b))

        root = et.Element("system")
        pd_a.render(root)
        pd_a_elem = root.find("protection_domain")
        assert pd_a_elem is not None
        cspace_elem = pd_a_elem.find("cspace")
        assert cspace_elem is not None
        tcb_cap_map_elem = cspace_elem.find("cap_tcb")
        assert tcb_cap_map_elem is not None
        assert tcb_cap_map_elem.get("pd") == "test_b"

    def test_sc_cap_map(self, sdf):
        pd_a = ProtectionDomain(sdf, "test_a", "test_a.elf", priority=100)
        pd_b = ProtectionDomain(sdf, "test_b", "test_b.elf", priority=100)

        pd_a.add_cap_map(SchedCxtCapMap(1, pd_b))

        root = et.Element("system")
        pd_a.render(root)
        pd_a_elem = root.find("protection_domain")
        assert pd_a_elem is not None
        cspace_elem = pd_a_elem.find("cspace")
        assert cspace_elem is not None
        tcb_cap_map_elem = cspace_elem.find("cap_sc")
        assert tcb_cap_map_elem is not None
        assert tcb_cap_map_elem.get("pd") == "test_b"

    def test_vspace_cap_map(self, sdf):
        pd_a = ProtectionDomain(sdf, "test_a", "test_a.elf", priority=100)
        pd_b = ProtectionDomain(sdf, "test_b", "test_b.elf", priority=100)

        pd_a.add_cap_map(VSpaceCapMap(1, pd_b))

        root = et.Element("system")
        pd_a.render(root)
        pd_a_elem = root.find("protection_domain")
        assert pd_a_elem is not None
        cspace_elem = pd_a_elem.find("cspace")
        assert cspace_elem is not None
        tcb_cap_map_elem = cspace_elem.find("cap_vspace")
        assert tcb_cap_map_elem is not None
        assert tcb_cap_map_elem.get("pd") == "test_b"
