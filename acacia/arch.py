# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ArchID(Enum):
    aarch64 = 1
    riscv64 = 2
    x86_64 = 3


@dataclass
class PageSize:
    name: str
    size_bytes: int

    def __post_init__(self):
        # must by a power of 2
        is_pow2 = lambda n: (n & (n - 1)) == 0
        assert is_pow2(self.size_bytes)

    def __eq__(self, value: object, /) -> bool:
        return value == self.size_bytes

    def addr_is_aligned(self, addr: int) -> bool:
        """
        Return true if the given address is aligned to page boundary
        """
        return addr % self.size_bytes == 0


SmallPage = PageSize(name="small", size_bytes=0x1000)

LargePage = PageSize("large", size_bytes=0x200000)

HugePage = PageSize("huge", size_bytes=0x40000000)

page_sizes = [SmallPage, LargePage, HugePage]


@dataclass
class Arch:
    """
    Representation of a system architecture.
    """

    arch: ArchID

    def is_arm(self) -> bool:
        return self.arch in [ArchID.aarch64]

    def is_riscv(self) -> bool:
        return self.arch in [ArchID.riscv64]

    def is_x86(self) -> bool:
        return self.arch in [ArchID.x86_64]

    def default_page_size(self) -> PageSize:
        # All architectures default to small pages
        return SmallPage

    def default_page_size_bytes(self) -> int:
        # All default to 0x1000 for now.
        return self.default_page_size().size_bytes

    def addr_is_page_aligned(
        self, addr: int, page_size: Optional[PageSize] = None
    ) -> bool:
        if page_size is None:
            page_size = self.default_page_size()
        return page_size.addr_is_aligned(addr)

    def roundup_to_page(self, n: int, page_size: Optional[PageSize] = None) -> int:
        if not page_size:
            page_size = self.default_page_size()
        p_sz = page_size.size_bytes
        return (n + p_sz - 1) & ~(p_sz - 1)

    def rounddown_to_page(self, n: int, page_size: Optional[PageSize] = None) -> int:
        if not page_size:
            page_size = self.default_page_size()
        p_sz = page_size.size_bytes
        return n - (n % p_sz)

    def determine_region_page_size(self, size: int) -> PageSize:
        # Round up to next page size
        for page_sz in sorted(page_sizes, key=lambda k: k.size_bytes, reverse=True):
            if size >= page_sz.size_bytes:
                return page_sz
        return page_sizes[0]


aarch64 = Arch(ArchID.aarch64)
riscv64 = Arch(ArchID.riscv64)
x86_64 = Arch(ArchID.x86_64)
