# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from enum import Enum
from typing import Optional

import pytest

from acacia import MemoryRegion
from acacia.arch import HugePage, LargePage, SmallPage, aarch64, x86_64


class TestArch:
    def test_aarch64_properties(self):
        assert not aarch64.is_riscv()
        assert aarch64.is_arm()

    def test_x86_64_properties(self):
        assert not x86_64.is_riscv()
        assert x86_64.is_x86()

    def test_default_page_size(self):
        assert aarch64.default_page_size_bytes() == 0x1000

    def test_addr_is_page_aligned(self):
        assert aarch64.addr_is_page_aligned(0x1000)
        assert aarch64.addr_is_page_aligned(0x2000)
        assert not aarch64.addr_is_page_aligned(0x1001)
        assert not aarch64.addr_is_page_aligned(0x500)

    def test_roundup_to_page(self):
        assert aarch64.roundup_to_page(0x500) == 0x1000
        assert aarch64.roundup_to_page(0x1000) == 0x1000
        assert aarch64.roundup_to_page(0x1001) == 0x2000
        assert aarch64.roundup_to_page(0x300000) == 0x300000

    def test_rounddown_to_page(self):
        assert aarch64.rounddown_to_page(0x500) == 0
        assert aarch64.rounddown_to_page(0x1000) == 0x1000
        assert aarch64.rounddown_to_page(0x1FFF) == 0x1000

    def test_page_size_alignment(self):
        assert SmallPage.addr_is_aligned(0)
        assert SmallPage.addr_is_aligned(0x1000)
        assert not SmallPage.addr_is_aligned(0x1001)

        assert LargePage.addr_is_aligned(0x200000)
        assert not LargePage.addr_is_aligned(0x201000)

        assert HugePage.addr_is_aligned(0x40000000)
        assert not HugePage.addr_is_aligned(0x200000)

    def test_addr_is_page_aligned_with_page_size(self):
        assert aarch64.addr_is_page_aligned(0x200000, LargePage)
        assert not aarch64.addr_is_page_aligned(0x201000, LargePage)

        assert aarch64.addr_is_page_aligned(0x40000000, HugePage)
        assert not aarch64.addr_is_page_aligned(0x40200000, HugePage)

    def test_roundup_to_large_page(self):
        assert aarch64.roundup_to_page(0, LargePage) == 0
        assert aarch64.roundup_to_page(0x1000, LargePage) == 0x200000
        assert aarch64.roundup_to_page(0x200000, LargePage) == 0x200000
        assert aarch64.roundup_to_page(0x200001, LargePage) == 0x400000

    def test_rounddown_to_large_page(self):
        assert aarch64.rounddown_to_page(0x1000, LargePage) == 0
        assert aarch64.rounddown_to_page(0x200000, LargePage) == 0x200000
        assert aarch64.rounddown_to_page(0x3FFFFF, LargePage) == 0x200000

    def test_determine_region_page_size(self):
        assert aarch64.determine_region_page_size(0) == SmallPage
        assert aarch64.determine_region_page_size(0xFFF) == SmallPage
        assert aarch64.determine_region_page_size(0x1000) == SmallPage
        assert aarch64.determine_region_page_size(0x1FFFFF) == SmallPage

        assert aarch64.determine_region_page_size(0x200000) == LargePage
        assert aarch64.determine_region_page_size(0x3FFFFFFF) == LargePage

        assert aarch64.determine_region_page_size(0x40000000) == HugePage
        assert aarch64.determine_region_page_size(0x80000000) == HugePage
