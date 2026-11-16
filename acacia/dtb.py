# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import struct
from abc import ABC, abstractstaticmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import libfdt  # type: ignore

from .arch import Arch
from .irq import IRQ, ConventionalIRQ
from .util import ctz


class DTB_IRQ_Controller(ABC):
    """
    This is an abstract base class representing different kinds of interrupt controller.
    This is currently a stub and is only implemented by Arm_GIC, but we want to preserve
    this interface for future expansion.
    """

    @classmethod
    def create(
        cls, arch: Arch, dtb: "DeviceTreeBlob"
    ) -> Optional["DTB_IRQ_Controller"]:
        """
        Create an instance of the interrupt controller based upon the Device Tree Blob.

        :param arch: Target system architecture, e.g. aarch64
        :param dtb: DTB for target system
        :returns: `DTB_IRQ_Controller` instance.
        """
        ...


class GicFrame(NamedTuple):
    """One of a GIC's MMIO frames: its exact CPU physical address and its size."""

    paddr: int
    size: int

    @property
    def end(self) -> int:
        return self.paddr + self.size


# See https://github.com/torvalds/linux/blob/v7.3/Documentation/devicetree/bindings/interrupt-controller/arm%2Cgic.yaml
# and https://github.com/torvalds/linux/blob/v7.3/Documentation/devicetree/bindings/interrupt-controller/arm%2Cgic-v3.yaml
# for more details on this ARM GIC decoder.
_GIC_V2_COMPATIBLES = ("arm,gic-400", "arm,cortex-a15-gic", "arm,gic-v2")
_GIC_V3_COMPATIBLES = ("arm,gic-v3",)


@dataclass(frozen=True)
class Arm_GIC(DTB_IRQ_Controller):
    """
    An ARM Generic Interrupt Controller, as described by a DTB's GIC node.

    Each MMIO frame is a GicFrame, or None if the node doesn't describe it:

    * dist (GICD): the distributor.
    * redists (GICR): GICv3 only. One frame per redistributor region, each
      holding the redistributors of a contiguous run of CPUs.
    * cpu (GICC): the MMIO CPU interface. Always present on GICv2. Optional on
      GICv3, where the CPU interface is the ICC_* system registers.
    * hyp (GICH) and vcpu (GICV): the virtualisation extensions' control and
      virtual CPU interfaces. Optional on GICv2, where they only exist if the
      DT describes the virtualisation extensions. Optional on GICv3, where
      they only exist if the GIC supports GICv2 compatibility, and are
      otherwise the ICH_* system registers.

    The Microkit assumes every ARM board has the virtualisation extensions, so
    a host DT for a GICv2 board should always have hyp and vcpu. But this class
    also parses guest DTs, which don't need to describe them, so it's up to the
    caller to check that they're there when it needs them.

    All addresses are CPU physical addresses, i.e. translated through any bus
    'ranges' between the GIC node and the root.

    For our (primarily userspace VMM) purpose, we need to know where the guest
    expects the dist and redists. Then for the cpu interface, we map the host's
    vcpu interface to where the guest expects the cpu interface.
    """

    class Version(IntEnum):
        V2 = 2
        V3 = 3

    version: "Arm_GIC.Version"
    dist: GicFrame
    cpu: Optional[GicFrame] = None
    hyp: Optional[GicFrame] = None
    vcpu: Optional[GicFrame] = None
    redists: Tuple[GicFrame, ...] = ()
    # GICv3 only: 'redistributor-stride', if the redistributors are padded
    # apart by quirky SoC rather than packed at their architectural size.
    redist_stride: Optional[int] = None

    def has_mmio_cpu_interface(self) -> bool:
        """Whether the CPU interface and the vCPU interface is MMIO rather than system registers."""
        return self.cpu is not None

    @classmethod
    def create(cls, arch: Arch, dtb: "DeviceTreeBlob") -> Optional["Arm_GIC"]:
        """
        Finds and parses the first GIC node from the device tree.
        """
        for node in dtb.nodes.values():
            version = _gic_version(dtb.get_compatible(node))
            if version is not None:
                return cls._from_node(arch, dtb, node, version)
        return None

    @classmethod
    def _from_node(
        cls,
        arch: Arch,
        dtb: "DeviceTreeBlob",
        node: "DTBNode",
        version: "Arm_GIC.Version",
    ) -> "Arm_GIC":
        where = f"GIC node '{node.path}'"
        frames = [
            _gic_frame(arch, dtb, node, addr, size)
            for addr, size in dtb.get_node_regs(node)
        ]

        if version == cls.Version.V2:
            # reg = <GICD>, <GICC>, then optionally <GICH>, <GICV>
            # (virtualisation extensions only).
            if not 2 <= len(frames) <= 4:
                raise ValueError(
                    f"{where}: GICv2 'reg' needs GICD, GICC and optionally "
                    f"GICH and GICV, but has {len(frames)} entries."
                )
            dist, cpu, *virt = frames
            hyp, vcpu = virt + [None] * (2 - len(virt))
            return cls(version, dist, cpu=cpu, hyp=hyp, vcpu=vcpu)

        # reg = <GICD>, <GICR> for each of #redistributor-regions,
        # then optionally <GICC>, <GICH>, <GICV> (GICv2 compatibility only).
        num_redists = _gic_int_prop(dtb, node, "#redistributor-regions", default=1)
        rest = frames[1 + num_redists :]
        if num_redists < 1 or len(rest) > 3 or len(frames) < 1 + num_redists:
            raise ValueError(
                f"{where}: GICv3 'reg' needs GICD, {num_redists} GICR region(s) "
                f"and up to 3 of GICC, GICH and GICV, but has {len(frames)} "
                "entries. Is '#redistributor-regions' correct?"
            )
        dist = frames[0]
        redists = tuple(frames[1 : 1 + num_redists])
        cpu, hyp, vcpu = rest + [None] * (3 - len(rest))
        return cls(
            version,
            dist,
            cpu=cpu,
            hyp=hyp,
            vcpu=vcpu,
            redists=redists,
            redist_stride=_gic_int_prop(
                dtb, node, "redistributor-stride", default=None
            ),
        )


def _gic_version(compatibles: List[str]) -> Optional[Arm_GIC.Version]:
    if any(c in _GIC_V3_COMPATIBLES for c in compatibles):
        return Arm_GIC.Version.V3
    if any(c in _GIC_V2_COMPATIBLES for c in compatibles):
        return Arm_GIC.Version.V2
    return None


def _gic_frame(
    arch: Arch, dtb: "DeviceTreeBlob", node: "DTBNode", addr: int, size: int
) -> GicFrame:
    page_offset = addr & (arch.default_page_size_bytes() - 1)
    return GicFrame(dtb.get_reg_paddr(arch, node, addr) + page_offset, size)


def _gic_int_prop(
    dtb: "DeviceTreeBlob", node: "DTBNode", name: str, default: Optional[int]
) -> Optional[int]:
    raw = dtb.get_node_prop(node, name)
    return default if raw is None else int.from_bytes(bytes(raw), "big")


def _arm_gic_irq_type(irq_type_val: int) -> str:
    return {
        0x0: "spi",
        0x1: "ppi",
        0x2: "extended_spi",
        0x3: "extended_ppi",
    }.get(irq_type_val, "unknown")


def _arm_gic_irq_number(number: int, irq_type: str) -> int:
    if irq_type == "spi":
        return number + 32
    if irq_type == "ppi":
        return number + 16
    raise RuntimeError(f"Unsupported IRQ type for number offset: {irq_type}")


def _arm_gic_trigger(trigger: int) -> IRQ.Trigger:
    # Only bits 0-3 are for the trigger
    t = trigger & 0xF
    if t in [0x1, 0x2]:
        return IRQ.Trigger.EDGE
    if t in [0x4, 0x8]:
        return IRQ.Trigger.LEVEL
    raise RuntimeError(f"Unexpected trigger value: {trigger}")


@dataclass
class DTBNode:
    """
    A representation of a Device Tree node as discovered at runtime.
    """

    offset: int
    path: str

    @property
    def name(self) -> str:
        """
        Return the name of this node ... i.e. the final term in the path.
        """
        if self.path == "/":
            return ""
        return self.path.rsplit("/", 1)[-1]


class DeviceTreeBlob:
    """
    Class encapsulating operations on a device tree. This class parses the DTB using
    pylibfdt and offers a friendly interface for using it for drivers and other OS
    functionality.

    The DTB is immediately parsed on `__init__`.
    """

    def __init__(self, dtb_file_path: str):
        self.file_path = dtb_file_path
        with open(self.file_path, mode="rb") as f:
            self.fdt = libfdt.Fdt(f.read())

        # libfdt makes nothing easy for us. enumerate!
        self.nodes: Dict[Tuple[int], DTBNode] = {}  # offset -> DTBNode
        self.__enumerate_nodes()

    def __enumerate_nodes(self):
        offset = -1
        DEPTH = ((1 << 32) // 2) - 1  # int32 sized ... underlying type is int
        while True:
            # Enumerate until we get a bogus offset (out of bounds)
            # There is probably a better way to do this, but it's not
            # really clear... this lib is undocumented!
            offset, _ = self.fdt.next_node(offset, DEPTH)
            try:
                path = self.fdt.get_path(offset)
            except libfdt.FdtException:
                break  # No more to enumerate
            self.nodes[offset] = DTBNode(offset, path)

    def get_compatible(self, node: DTBNode) -> List[str]:
        """
        Return list of compatible strings in (hopefully) human readable
        form, (hopefully) identical to DTS
        """
        if self.fdt.hasprop(node.offset, "compatible"):
            return [
                x.decode()
                for x in self.get_node_prop(node, "compatible").split(b"\x00")
                if len(x) != 0
            ]
        return []

    def get_nodes_by_compatible(self, compatible_str) -> List[DTBNode]:
        """
        Try find a node with a matching compatible string.
        """
        return [
            n for n in self.nodes.values() if compatible_str in self.get_compatible(n)
        ]

    def get_node_by_path(self, path_str: str) -> DTBNode:
        """
        Given a path string (e.g. /soc/serial@3002000), attempt to find a matching node.
        """
        # defensive: enforce that path starts with /
        if path_str[0] != "/":
            path_str = "/" + path_str
        return DTBNode(self.fdt.path_offset(path_str), path_str)

    def get_node_prop(self, node: DTBNode, prop_name: str):
        """
        Get a property from a DTB node given a property name. This will
        return the raw contents of the property as a bytearray.

        Returns None if property doesn't exist
        """
        if self.fdt.hasprop(node.offset, prop_name):
            return self.fdt.getprop(node.offset, prop_name)
        return None

    def get_node_parent(self, node: DTBNode) -> DTBNode:
        """
        Get the parent of a node if it exists.
        """
        return self.nodes[self.fdt.parent_offset(node.offset)]

    def get_size_and_addr_cells(self, node: DTBNode) -> Tuple[int, int]:
        """
        Get the size and addr cells values of a node (node its parent).

        :returns: `(size cells, addr cells)`
        """
        if self.fdt.hasprop(node.offset, "#size-cells"):
            out_size = self.get_node_prop(node, "#size-cells").as_uint32()
        else:
            # DTS spec default
            out_size = 1
        if self.fdt.hasprop(node.offset, "#size-cells"):
            out_addr = self.get_node_prop(node, "#address-cells").as_uint32()
        else:
            # DTS spec default
            out_addr = 2

        return (out_size, out_addr)

    def get_node_regs(self, node: DTBNode) -> List[Tuple]:
        """
        Given a node, read its regs array and return a list of tuples.
        Tuples are (addr, len) pairs. This method automatically parses
        the parent node to figure out the appropriate size of members.
        """
        size_cells, addr_cells = self.get_size_and_addr_cells(
            self.get_node_parent(node)
        )

        regs_raw = self.get_node_prop(node, "reg")
        if regs_raw is None:
            raise RuntimeError(f"Node {node} has no regs property, cannot get regs!")
        if len(regs_raw) % 4 != 0:
            raise RuntimeError(f"Regs field {regs_raw} isn't 32 bit aligned!")

        # This is an array of structs ... we need to figure out the size
        # of the struct to de-serialise it correctly.
        # DTBs are always big endian!
        num_u32s = len(regs_raw) // 4
        vals = struct.unpack(f">{num_u32s}I", regs_raw)

        # Group fields +
        # merge u32s in field to create appropriately sized words
        # note: assumes MSW in w_l[0]
        def merge_u32s(w_l):
            return sum(x << (32 * (len(w_l) - i - 1)) for i, x in enumerate(w_l))

        regs = [
            (
                merge_u32s(vals[i : i + addr_cells]),  # addr
                merge_u32s(vals[i + addr_cells : i + size_cells + addr_cells]),  # size
            )
            for i in range(0, len(vals), size_cells + addr_cells)
        ]
        return regs

    def get_node_irqs(self, node: DTBNode) -> Tuple[int, ...]:
        """
        Return the list of words from the IRQ field on a node. We don't
        attempt to concetenate the u32s or anything here, since the meaning
        of the field is entirely dependent on architecture.
        """
        # TODO: should we handle extended-interrupts? The DTS spec implies
        # we should use extended instead of interrupts if it exists.
        # Old sdfgen didn't do this either.
        irqs_raw = self.get_node_prop(node, "interrupts")

        # If no interrupts, try get `interrupt` instead.
        if irqs_raw is None:
            irqs_raw = self.get_node_prop(node, "interrupt")

        num_u32s = len(irqs_raw) // 4
        # otherwise: doomed
        if irqs_raw is None:
            raise RuntimeError(f"{node} has no IRQs!")

        # just a bunch of u32s ... unpack using struct and return
        return struct.unpack(f">{num_u32s}I", irqs_raw)

    def get_parsed_irqs(self, node: DTBNode, arch: Arch) -> Sequence[IRQ]:
        """
        Parses the 'interrupts' property of a node into a list of IRQ objects.
        """
        raw_irqs = self.get_node_irqs(node)
        parsed = []

        # Determine number of cells per interrupt based on architecture
        # Zig logic implies hardcoding expected cells
        min_cells_per_irq = 3 if arch.is_arm() else 1 if arch.is_riscv() else 0

        if min_cells_per_irq == 0:
            raise RuntimeError("Unsupported architecture for IRQ parsing")

        if (n := len(raw_irqs)) % min_cells_per_irq != 0:
            # TODO: replace with logging module
            print(
                f"WARNING: IRQ for {node} has {n} interrupt cells when this arch expects multiples "
                f"of {min_cells_per_irq}. Dropping remainder."
            )
            raw_irqs = raw_irqs[: n - (n % min_cells_per_irq)]
            assert len(raw_irqs) % min_cells_per_irq == 0

        for i in range(0, len(raw_irqs), min_cells_per_irq):
            irq_cells = list(raw_irqs[i : i + min_cells_per_irq])
            parsed.append(_parse_irq(arch, irq_cells))

        return parsed

    def get_reg_paddr(self, arch: Arch, node: DTBNode, paddr: int) -> int:
        """
        Given an address from a DTB node's 'reg' property, convert it to a
        mappable MMIO address. This involves traversing any higher-level busses
        to find the CPU visible address rather than some address relative to the
        particular bus the address is on. We also align to the smallest page size.
        """
        page_bits = ctz(arch.default_page_size_bytes())

        # align page size
        device_paddr = paddr & ~((1 << page_bits) - 1)

        # Walk tree
        curr_node = node
        while True:
            try:
                parent = self.get_node_parent(curr_node)
            except (KeyError, libfdt.FdtException):
                # Reached root or error
                break

            if self.fdt.hasprop(parent.offset, "ranges"):
                ranges_raw = self.get_node_prop(parent, "ranges")

                # Check if empty ranges property (implies 1:1 mapping for this bus)
                if len(ranges_raw) == 0:
                    curr_node = parent
                    continue

                # We need to parse 'ranges'
                # Format:
                # child-bus-addr (parent addr cells)
                # parent-bus-addr (grandparent addr cells)
                # length (parent size cells)

                p_size_cells, p_addr_cells = self.get_size_and_addr_cells(parent)

                try:
                    grandparent = self.get_node_parent(parent)
                    _, gp_addr_cells = self.get_size_and_addr_cells(grandparent)
                except (KeyError, libfdt.FdtException):
                    # Root bus? Assume 2 address cells for the 'system' bus
                    gp_addr_cells = 2

                entry_cells = p_addr_cells + gp_addr_cells + p_size_cells
                if len(ranges_raw) % (entry_cells * 4) != 0:
                    # Malformed ranges property, skip?
                    curr_node = parent
                    continue

                vals = struct.unpack(f">{len(ranges_raw)//4}I", ranges_raw)
                num_entries = len(vals) // entry_cells

                for i in range(num_entries):
                    idx = i * entry_cells

                    # Extract child Address
                    child_addr = 0
                    for j in range(p_addr_cells):
                        child_addr = (child_addr << 32) | vals[idx + j]

                    # Extract parent Address
                    parent_addr = 0
                    for j in range(gp_addr_cells):
                        parent_addr = (parent_addr << 32) | vals[idx + p_addr_cells + j]

                    # Extract kength
                    length = 0
                    for j in range(p_size_cells):
                        length = (length << 32) | vals[
                            idx + p_addr_cells + gp_addr_cells + j
                        ]

                    # Check if paddr falls in this range
                    if child_addr <= device_paddr < child_addr + length:
                        offset = device_paddr - child_addr
                        device_paddr = parent_addr + offset
                        break  # tranlated for this level

            curr_node = parent
        # TODO: make sure this works...

        return device_paddr


def _parse_irq(arch: Arch, irq_cells: List[int]) -> ConventionalIRQ:
    """
    Parses a list of u32s representing a single IRQ into an IRQ object.
    """
    if arch.is_arm():
        if len(irq_cells) < 3:
            raise RuntimeError(
                f"Expected at least 3 interrupt cells for ARM, found {len(irq_cells)}"
            )

        i_type = _arm_gic_irq_type(irq_cells[0])
        num = _arm_gic_irq_number(irq_cells[1], i_type)
        trigger = _arm_gic_trigger(irq_cells[2])
        return ConventionalIRQ(num, trigger)

    if arch.is_riscv():
        if len(irq_cells) != 1:
            raise RuntimeError(
                f"RISC-V expected 1 interrupt cell, found {len(irq_cells)}"
            )
        # RISC-V usually implies level triggered, defaults in spec often not strict
        return ConventionalIRQ(irq_cells[0], IRQ.Trigger.LEVEL)

    raise RuntimeError(f"Unsupported architecture for IRQ parsing: {arch.arch}")
