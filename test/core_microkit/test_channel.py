# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
import xml.etree.ElementTree as et
from acacia.channel import Channel
from acacia.pd import ProtectionDomain


class TestChannelEnd:
    def test_ch_id_range_check_low(self):
        with pytest.raises(ValueError, match="Invalid channel id"):
            Channel.End(pd=None, can_notify=True, can_pp=False, ch_id=-1)

    def test_ch_id_range_check_high(self):
        with pytest.raises(ValueError, match="Invalid channel id"):
            Channel.End(pd=None, can_notify=True, can_pp=False, ch_id=256)


class TestChannel:
    def create_pd(self, name, priority):
        return ProtectionDomain(name, f"{name}.elf", priority=priority)

    def test_valid_channel_creation(self):
        pd1 = self.create_pd("pd1", 100)
        pd2 = self.create_pd("pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=False)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False)
        ch = Channel(end_a, end_b)
        assert ch.end_a.pd == pd1
        assert ch.end_b.pd == pd2

    def test_ppc_low_to_high_priority(self):
        """PPC from low priority to high priority should work"""
        low_pd = self.create_pd("low", 100)
        high_pd = self.create_pd("high", 200)
        end_a = Channel.End(pd=low_pd, can_notify=True, can_pp=True)  # Low calls high
        end_b = Channel.End(pd=high_pd, can_notify=True, can_pp=False)
        ch = Channel(end_a, end_b)  # Should not raise
        assert ch.end_a.can_pp

    def test_ppc_high_to_low_rejected(self):
        """PPC from high priority to low priority should fail"""
        high_pd = self.create_pd("high", 200)
        low_pd = self.create_pd("low", 100)
        end_a = Channel.End(pd=high_pd, can_notify=True, can_pp=True)  # High calls low - invalid
        end_b = Channel.End(pd=low_pd, can_notify=True, can_pp=False)
        with pytest.raises(RuntimeError, match="PPCs can only go from low to high"):
            Channel(end_a, end_b)

    def test_ppc_same_priority_rejected(self):
        """PPC between same priorities should fail"""
        pd1 = self.create_pd("pd1", 100)
        pd2 = self.create_pd("pd2", 100)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=True)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False)
        with pytest.raises(RuntimeError, match="PPCs can only go from low to high"):
            Channel(end_a, end_b)

    def test_channel_id_allocation(self):
        pd1 = self.create_pd("pd1", 100)
        pd2 = self.create_pd("pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=False, ch_id=None)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=None)
        Channel(end_a, end_b)
        # IDs should have been allocated
        assert end_a.ch_id is not None
        assert end_b.ch_id is not None
        assert end_a.ch_id in pd1.assigned_ids
        assert end_b.ch_id in pd2.assigned_ids

    def test_channel_id_respected(self):
        pd1 = self.create_pd("pd1", 100)
        pd2 = self.create_pd("pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=False, ch_id=5)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=10)
        Channel(end_a, end_b)
        assert end_a.ch_id == 5
        assert end_b.ch_id == 10

    def test_render(self):
        pd1 = self.create_pd("pd1", 100)
        pd2 = self.create_pd("pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=True, can_pp=True, ch_id=1)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=2)
        ch = Channel(end_a, end_b)
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

    def test_render_notify_false(self):
        pd1 = self.create_pd("pd1", 100)
        pd2 = self.create_pd("pd2", 200)
        end_a = Channel.End(pd=pd1, can_notify=False, can_pp=False, ch_id=1)
        end_b = Channel.End(pd=pd2, can_notify=True, can_pp=False, ch_id=2)
        ch = Channel(end_a, end_b)
        root = et.Element("system")
        ch.render(root)
        ends = root.find("channel").findall("end")
        pd1_end = next(e for e in ends if e.get("pd") == "pd1")
        assert pd1_end.get("notify") == "false"

