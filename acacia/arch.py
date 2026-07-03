# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
from typing import Optional
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as et


class ArchID(Enum):
    aarch32 = 1
    aarch64 = 2
    riscv32 = 3
    riscv64 = 4
    x86 = 5
    x86_64 = 6


class PageSizeID(Enum):
    small = 1
    large = 2


@dataclass
class Arch:
    """
    Representation of a system architecture.
    """

    arch: ArchID

    def is_arm(self) -> bool:
        return self.arch in [ArchID.aarch32, ArchID.aarch64]

    def is_riscv(self) -> bool:
        return self.arch in [ArchID.riscv32, ArchID.riscv64]

    def is_x86(self) -> bool:
        return self.arch in [ArchID.x86, ArchID.x86_64]

    def is_64_bit(self) -> bool:
        return self.arch in [ArchID.aarch64, ArchID.riscv64, ArchID.x86_64]

    def default_page_size(self) -> int:
        # All default to 0x1000 for now.
        return 0x1000

    def addr_is_page_aligned(self, addr: int) -> bool:
        return (addr % self.default_page_size()) == 0

    def roundup_to_page(self, n: int) -> int:
        p_sz = self.default_page_size()
        return n if n % p_sz == 0 else n + p_sz - (n % p_sz)

    def rounddown_to_page(self, n: int) -> int:
        p_sz = self.default_page_size()
        return n - (n % p_sz)

    def get_page_size(self, page_size: PageSizeID) -> int:
        if page_size is PageSizeID.small:
            return 0x1000
        if page_size is PageSizeID.large:
            return 0x200000 if self.is_64_bit() else 0x400000
        raise RuntimeError("Invalid page size ID!")


aarch64 = Arch(ArchID.aarch64)
aarch32 = Arch(ArchID.aarch32)
riscv64 = Arch(ArchID.riscv64)
riscv32 = Arch(ArchID.riscv32)
x86 = Arch(ArchID.x86)
x86_64 = Arch(ArchID.x86_64)


class SDFMemoryAllocator:
    """
    Class encapsulating the physical memory map of the system.
    Used for assigning physical addresses to physical MRs
    """

    def __init__(self, arch: Arch, paddr_top: int):
        self.arch = arch
        self.paddr_top = paddr_top

    def allocate(self, sz) -> int:
        self.paddr_top = self.paddr_top - sz
        return self.paddr_top
