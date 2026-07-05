# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import struct
from abc import ABC, abstractstaticmethod
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional, Sequence
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

    @abstractstaticmethod
    def create(arch: Arch, dtb: "DeviceTreeBlob"):
        """
        Create an instance of the interrupt controller based upon the Device Tree Blob.
        Args:
            arch: Arch - Target system architecture, e.g. aarch64
            dtb: DeviceTreeBlob - DTB for target system
        Returns:
            DTB_IRQ_Controller instance.
        """
        ...


class Arm_GIC(DTB_IRQ_Controller):
    """
    Representation of the ARM Generic Interrupt Controller.
    """

    class Version:
        V2 = 2
        V3 = 3

    def __init__(
        self,
        version: int,
        cpu_paddr: Optional[int] = None,
        vcpu_paddr: Optional[int] = None,
        vcpu_size: Optional[int] = None,
    ):
        self.version = version
        self.cpu_paddr = cpu_paddr
        self.vcpu_paddr = vcpu_paddr
        self.vcpu_size = vcpu_size

    def has_mmio_cpu_interface(self) -> bool:
        """
        Whether or not the GIC's CPU/vCPU interface is via MMIO.
        """
        return self.cpu_paddr is not None

    @staticmethod
    def create(arch: Arch, dtb: "DeviceTreeBlob") -> Optional["Arm_GIC"]:
        """
        Finds and parses the GIC node from the device tree.
        """
        compat_v2 = ["arm,gic-v2", "arm,cortex-a15-gic", "arm,gic-400"]
        compat_v3 = ["arm,gic-v3"]
        all_compat = compat_v2 + compat_v3

        # Find the GIC node
        gic_node = None
        for node in dtb.nodes.values():
            node_comp = dtb.get_compatible(node)
            if any(c in node_comp for c in all_compat):
                gic_node = node
                break

        if gic_node is None:
            return None

        # Determine version
        node_comp = dtb.get_compatible(gic_node)
        if any(c in node_comp for c in compat_v2):
            version = Arm_GIC.Version.V2
        elif any(c in node_comp for c in compat_v3):
            version = Arm_GIC.Version.V3
        else:
            raise RuntimeError(
                "Unable to determine GIC version from compatible strings"
            )

        # Parse registers
        # GICv2: 0=Distributor, 1=CPU, 2=virtual CPU, 3=Hypervisor
        # GICv3: 0=Distributor, 1=Redistributor, 2=CPU, 3=..., 4=virtual CPU
        cpu_reg_idx = 1 if version == Arm_GIC.Version.V2 else 2
        vcpu_reg_idx = 3 if version == Arm_GIC.Version.V2 else 4

        regs = dtb.get_node_regs(gic_node)

        cpu_paddr = None
        vcpu_paddr = None
        vcpu_size = None

        if cpu_reg_idx < len(regs):
            cpu_paddr = dtb.get_reg_paddr(arch, gic_node, regs[cpu_reg_idx][0])

        if vcpu_reg_idx < len(regs):
            vcpu_paddr = dtb.get_reg_paddr(arch, gic_node, regs[vcpu_reg_idx][0])
            vcpu_size = regs[vcpu_reg_idx][1]

        return Arm_GIC(version, cpu_paddr, vcpu_paddr, vcpu_size)


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
    offset: int
    path: str


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


class DeviceTreeBlob:
    """
    Class encapsulating operations on a device tree.
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
        # defensive: enforce that path starts with /
        if path_str[0] != "/":
            path_str = "/" + path_str
        return DTBNode(self.fdt.path_offset(path_str), path_str)

    def get_node_prop(self, node: DTBNode, prop_name: str):
        """
        Get a property from a DTB node. This will return the
        raw contents of the property as a bytearray.

        Returns None if property doesn't exist
        """
        if self.fdt.hasprop(node.offset, prop_name):
            return self.fdt.getprop(node.offset, prop_name)
        return None

    def get_node_parent(self, node: DTBNode) -> DTBNode:
        return self.nodes[self.fdt.parent_offset(node.offset)]

    def get_size_and_addr_cells(self, node: DTBNode) -> Tuple[int, int]:
        """
        Get the size and addr cells values of a node (node its parent).
        Returns:
            Tuple[int,int]: (size cells, addr cells)
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

    def get_node_irqs(self, node: DTBNode) -> Tuple[int, int]:
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
        cells_per_irq = 3 if arch.is_arm() else 1 if arch.is_riscv() else 0

        if cells_per_irq == 0:
            raise RuntimeError("Unsupported architecture for IRQ parsing")

        if len(raw_irqs) % cells_per_irq != 0:
            raise RuntimeError(
                f"Raw IRQ data length {len(raw_irqs)} is not a multiple of expected cell count {cells_per_irq}"
            )

        for i in range(0, len(raw_irqs), cells_per_irq):
            irq_cells = list(raw_irqs[i : i + cells_per_irq])
            parsed.append(_parse_irq(arch, irq_cells))

        return parsed

    def get_reg_paddr(self, arch: Arch, node: DTBNode, paddr: int) -> int:
        """
        Given an address from a DTB node's 'reg' property, convert it to a
        mappable MMIO address. This involves traversing any higher-level busses
        to find the CPU visible address rather than some address relative to the
        particular bus the address is on. We also align to the smallest page size.
        """
        page_bits = ctz(arch.default_page_size())

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

                p_addr_cells, p_size_cells = self.get_size_and_addr_cells(parent)

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
