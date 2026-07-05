# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from unittest.mock import MagicMock
from acacia.channel import Channel
from acacia.pd import ProtectionDomain


@pytest.fixture
def sdf():
    """A stand-in System for entity constructors."""
    return MagicMock(name="sdf")


class TestChannelEnd:
    def test_ch_id_range_check_low(self):
        with pytest.raises(ValueError, match="Invalid channel id"):
            Channel.End(pd=None, can_notify=True, can_pp=False, ch_id=-1)

    def test_ch_id_range_check_high(self):
        with pytest.raises(ValueError, match="Invalid channel id"):
            Channel.End(pd=None, can_notify=True, can_pp=False, ch_id=256)


class TestChannel:
    def create_pd(self, sdf, name, priority):
        return ProtectionDomain(name, f"{name}.elf", sdf, priority=priority)

    def test_valid_channel_creation(self, sdf):
        pd1 = self.create_pd(sdf, "pd1", 100)
        pd2 = self.create_pd(sdf, "pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=False)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False)
        ch = Channel(end_a, end_b, sdf)
        assert ch.end_a.pd == pd1
        assert ch.end_b.pd == pd2

    def test_ppc_low_to_high_priority(self, sdf):
        """PPC from low priority to high priority should work"""
        low_pd = self.create_pd(sdf, "low", 100)
        high_pd = self.create_pd(sdf, "high", 200)
        end_a = Channel.End(pd=low_pd, can_notify=True, can_pp=True)  # Low calls high
        end_b = Channel.End(pd=high_pd, can_notify=True, can_pp=False)
        ch = Channel(end_a, end_b, sdf)  # Should not raise
        assert ch.end_a.can_pp

    def test_ppc_high_to_low_rejected(self, sdf):
        """PPC from high priority to low priority should fail"""
        high_pd = self.create_pd(sdf, "high", 200)
        low_pd = self.create_pd(sdf, "low", 100)
        end_a = Channel.End(
            pd=high_pd, can_notify=True, can_pp=True
        )  # High calls low - invalid
        end_b = Channel.End(pd=low_pd, can_notify=True, can_pp=False)
        with pytest.raises(RuntimeError):
            Channel(end_a, end_b, sdf)

    def test_ppc_same_priority_rejected(self, sdf):
        """PPC between same priorities should fail"""
        pd1 = self.create_pd(sdf, "pd1", 100)
        pd2 = self.create_pd(sdf, "pd2", 100)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=True)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False)
        with pytest.raises(RuntimeError):
            Channel(end_a, end_b, sdf)

    def test_channel_id_allocation(self, sdf):
        pd1 = self.create_pd(sdf, "pd1", 100)
        pd2 = self.create_pd(sdf, "pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=False, ch_id=None)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=None)
        Channel(end_a, end_b, sdf)
        # IDs should have been allocated
        assert end_a.ch_id is not None
        assert end_b.ch_id is not None

    def test_channel_id_respected(self, sdf):
        pd1 = self.create_pd(sdf, "pd1", 100)
        pd2 = self.create_pd(sdf, "pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=False, ch_id=5)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=10)
        Channel(end_a, end_b, sdf)
        assert end_a.ch_id == 5
        assert end_b.ch_id == 10

    def test_render(self, sdf):
        pd1 = self.create_pd(sdf, "pd1", 100)
        pd2 = self.create_pd(sdf, "pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=True, ch_id=1)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=2)
        ch = Channel(end_a, end_b, sdf)
        root = et.Element("system")
        ch.render(root)
        ch_elem = root.find("channel")
        assert ch_elem is not None

        ends = ch_elem.findall("end")
        assert len(ends) == 2

        # Find end for pd1
        pd1_end = next(e for e in ends if e.get("pd") == "pd1")
        assert pd1_end.get("id") == "1"
        assert pd1_end.get("notify") is None  # True is default, omitted
        assert pd1_end.get("pp") is "true"

        # Find end for pd2
        pd2_end = next(e for e in ends if e.get("pd") == "pd2")
        assert pd2_end.get("id") == "2"
        assert pd2_end.get("notify") is None  # True is default, omitted
        assert pd2_end.get("pp") == None

    def test_render_notify_false(self, sdf):
        pd1 = self.create_pd(sdf, "pd1", 100)
        pd2 = self.create_pd(sdf, "pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=False, can_pp=False, ch_id=1)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=2)
        ch = Channel(end_a, end_b, sdf)
        root = et.Element("system")
        ch.render(root)
        ends = root.find("channel").findall("end")
        pd1_end = next(e for e in ends if e.get("pd") == "pd1")
        assert pd1_end.get("notify") == "false"
