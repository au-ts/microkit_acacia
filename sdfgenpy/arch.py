# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
from typing import Optional
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as et

class ArchID(Enum):
    aarch32 = 0
    aarch64 = 1
    riscv32 = 2
    riscv64 = 3
    x86 = 4
    x86_64 = 5

class PageSizeID(Enum):
    small = 0
    large = 1

@dataclass
class Arch:
    """
    Representation of a system architecture.
    """
    arch: ArchID

    def is_arm(self) -> bool:
        return self.arch in [ArchID.aarch32, ArchId.aarch64]

    def is_riscv(self) -> bool:
        return self.arch in [ArchID.riscv32, ArchId.riscv64]

    def is_x86(self) -> bool:
        return self.arch in [ArchID.x86, ArchId.x86_64]

    def is_64_bit(self) -> bool:
        return self.arch in [ArchID.aarch64, ArchID.riscv64, ArchID.x86_64]

    def default_page_size(self) -> int:
        # All default to 0x1000 for now.
        return 0x1000

    def addr_is_page_aligned(self, addr: int) -> bool:
        return (addr % self.default_page_size()) == 0

    def roundup_to_page(self, n: int) -> int:
        p_sz = self.default_page_size()
        return p_sz if n < p_sz else n if n % p_sz == 0 else n + p_sz - (n % p_sz)

    def rounddown_to_page(self, n: int) -> int:
        p_sz = self.default_page_size()
        return 0 if n < p_sz else n if n % p_sz == 0 else n - (n % p_sz)

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
    Class encapsulating the memory map of the system. Used for:
    a. Assigning physical addresses to physical MRs,
    b. Assigning virtual addresses to maps,
    c. Containing valid page sizes.
    """
    def __init__(self, arch: Arch, paddr_top: int, page_sz):
        self.arch = arch
        self.paddr_top = paddr_top

    def paddr_top(self):
        return self.paddr_top

    def update_paddr_top(self, new):
        if new > self.paddr_top:
            raise RuntimeError("Paddr top should only decrement!")
        self.paddr_top = new

