# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import pytest
from typing import Optional
from acacia.arch import Arch, ArchID, PageSizeID, SDFMemoryAllocator
from acacia import aarch64, x86_64, riscv32
from enum import Enum


class TestArch:
    def test_aarch64_properties(self):
        assert aarch64.is_64_bit()
        assert not aarch64.is_riscv()
        assert aarch64.is_arm()

    def test_x86_64_properties(self):
        assert x86_64.is_64_bit()
        assert not x86_64.is_riscv()
        assert x86_64.is_x86()

    def test_default_page_size(self):
        assert aarch64.default_page_size() == 0x1000
        assert riscv32.default_page_size() == 0x1000

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

    def test_get_page_size_small(self):
        assert aarch64.get_page_size(PageSizeID.small) == 0x1000

    def test_get_page_size_large_64bit(self):
        assert aarch64.get_page_size(PageSizeID.large) == 0x200000

    def test_get_page_size_large_32bit(self):
        assert riscv32.get_page_size(PageSizeID.large) == 0x400000

    def test_get_page_size_invalid(self):
        # Create a fake page size ID
        class FakePageSize(Enum):
            huge = 2

        with pytest.raises(RuntimeError, match="Invalid page size"):
            aarch64.get_page_size(FakePageSize.huge)


class TestSDFMemoryAllocator:
    def test_initialization(self):
        alloc = SDFMemoryAllocator(aarch64, 0x80000000)
        assert alloc.paddr_top == 0x80000000
        assert alloc.arch == aarch64

    def test_update_paddr_top_decrements(self):
        alloc = SDFMemoryAllocator(aarch64, 0x80000000)
        alloc.update_paddr_top(0x70000000)
        assert alloc.paddr_top == 0x70000000

    def test_update_paddr_top_increase_rejected(self):
        alloc = SDFMemoryAllocator(aarch64, 0x80000000)
        with pytest.raises(RuntimeError, match="only decrement"):
            alloc.update_paddr_top(0x90000000)
