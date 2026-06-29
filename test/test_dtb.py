# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

import sys
import struct
from unittest.mock import MagicMock, patch, mock_open

import pytest

sys.modules.setdefault("libfdt", MagicMock())

import acacia.dtb as dtb_module
from acacia.dtb import (
    Arm_GIC,
    DTBNode,
    DeviceTreeBlob,
    _arm_gic_irq_type,
    _arm_gic_irq_number,
    _arm_gic_trigger,
    _parse_irq,
)
from acacia.irq import IRQ


class FakeFdtException(Exception):
    pass


fake_libfdt = MagicMock()
fake_libfdt.FdtException = FakeFdtException


@pytest.fixture(autouse=True)
def _patch_libfdt():
    with patch.object(dtb_module, "libfdt", fake_libfdt):
        yield


def _construct_blob(fdt):
    fake_libfdt.Fdt.return_value = fdt
    with patch("builtins.open", mock_open(read_data=b"\x00")):
        return DeviceTreeBlob("dummy.dtb")


@pytest.fixture
def fdt():
    f = MagicMock()
    f.next_node.return_value = (0, 0)
    f.get_path.side_effect = FakeFdtException()
    return f


@pytest.fixture
def blob(fdt):
    return _construct_blob(fdt)


@pytest.mark.parametrize("val,expected", [
    (0x0, "spi"),
    (0x1, "ppi"),
    (0x2, "extended_spi"),
    (0x3, "extended_ppi"),
    (0x99, "unknown"),
    (-1, "unknown"),
])
def test_arm_gic_irq_type(val, expected):
    assert _arm_gic_irq_type(val) == expected


def test_arm_gic_irq_number_spi():
    assert _arm_gic_irq_number(5, "spi") == 37


def test_arm_gic_irq_number_ppi():
    assert _arm_gic_irq_number(5, "ppi") == 21


def test_arm_gic_irq_number_zero_spi():
    assert _arm_gic_irq_number(0, "spi") == 32


@pytest.mark.parametrize("irq_type", ["extended_spi", "extended_ppi", "unknown"])
def test_arm_gic_irq_number_unsupported_type_raises(irq_type):
    with pytest.raises(RuntimeError, match="Unsupported IRQ type"):
        _arm_gic_irq_number(5, irq_type)


@pytest.mark.parametrize("val,expected", [
    (0x1, IRQ.Trigger.EDGE),
    (0x2, IRQ.Trigger.EDGE),
    (0x4, IRQ.Trigger.LEVEL),
    (0x8, IRQ.Trigger.LEVEL),
])
def test_arm_gic_trigger(val, expected):
    assert _arm_gic_trigger(val) == expected


def test_arm_gic_trigger_masks_high_bits():
    assert _arm_gic_trigger(0xF1) == IRQ.Trigger.EDGE
    assert _arm_gic_trigger(0xA4) == IRQ.Trigger.LEVEL


@pytest.mark.parametrize("val", [0x0, 0x3, 0xC])
def test_arm_gic_trigger_invalid_raises(val):
    with pytest.raises(RuntimeError, match="Unexpected trigger"):
        _arm_gic_trigger(val)


def test_parse_irq_arm():
    arch = MagicMock()
    arch.is_arm.return_value = True
    arch.is_riscv.return_value = False
    with patch.object(dtb_module, "ConventionalIRQ") as ci:
        _parse_irq(arch, [0, 5, 1])
        ci.assert_called_once_with(37, IRQ.Trigger.EDGE)


def test_parse_irq_arm_ppi_level():
    arch = MagicMock()
    arch.is_arm.return_value = True
    arch.is_riscv.return_value = False
    with patch.object(dtb_module, "ConventionalIRQ") as ci:
        _parse_irq(arch, [1, 3, 4])
        ci.assert_called_once_with(19, IRQ.Trigger.LEVEL)


def test_parse_irq_arm_insufficient_cells_raises():
    arch = MagicMock()
    arch.is_arm.return_value = True
    arch.is_riscv.return_value = False
    with pytest.raises(RuntimeError, match="at least 3 interrupt cells"):
        _parse_irq(arch, [0, 5])


def test_parse_irq_riscv():
    arch = MagicMock()
    arch.is_arm.return_value = False
    arch.is_riscv.return_value = True
    with patch.object(dtb_module, "ConventionalIRQ") as ci:
        _parse_irq(arch, [9])
        ci.assert_called_once_with(9, IRQ.Trigger.LEVEL)


def test_parse_irq_riscv_wrong_cell_count_raises():
    arch = MagicMock()
    arch.is_arm.return_value = False
    arch.is_riscv.return_value = True
    with pytest.raises(RuntimeError, match="expected 1 interrupt cell"):
        _parse_irq(arch, [1, 2])


def test_parse_irq_unsupported_arch_raises():
    arch = MagicMock()
    arch.is_arm.return_value = False
    arch.is_riscv.return_value = False
    arch.arch = "x86"
    with pytest.raises(RuntimeError, match="Unsupported architecture for IRQ parsing"):
        _parse_irq(arch, [1])


def test_dtbnode_fields():
    n = DTBNode(5, "/foo")
    assert n.offset == 5
    assert n.path == "/foo"


def test_dtbnode_equality():
    assert DTBNode(1, "/a") == DTBNode(1, "/a")
    assert DTBNode(1, "/a") != DTBNode(2, "/a")


def test_arm_gic_version_constants():
    assert Arm_GIC.Version.V2 == 2
    assert Arm_GIC.Version.V3 == 3


def test_arm_gic_init_stores_fields():
    gic = Arm_GIC(3, 0x1000, 0x2000, 0x40)
    assert gic.version == 3
    assert gic.cpu_paddr == 0x1000
    assert gic.vcpu_paddr == 0x2000
    assert gic.vcpu_size == 0x40


def test_arm_gic_has_mmio_cpu_interface_true():
    gic = Arm_GIC(2, 0x1000, None, None)
    assert gic.has_mmio_cpu_interface() is True


def test_arm_gic_has_mmio_cpu_interface_false():
    gic = Arm_GIC(2, None, None, None)
    assert gic.has_mmio_cpu_interface() is False


def test_arm_gic_create_no_node_returns_none():
    arch = MagicMock()
    dtb = MagicMock()
    dtb.nodes = {0: MagicMock()}
    dtb.get_compatible.return_value = ["foo,bar"]
    assert Arm_GIC.create(arch, dtb) is None


def test_arm_gic_create_v2():
    arch = MagicMock()
    dtb = MagicMock()
    node = MagicMock()
    dtb.nodes = {0: node}
    dtb.get_compatible.return_value = ["arm,gic-400"]
    dtb.get_node_regs.return_value = [
        (0x1000, 0x10),
        (0x2000, 0x20),
        (0x3000, 0x30),
        (0x4000, 0x40),
    ]
    dtb.get_reg_paddr.side_effect = lambda a, n, addr: addr

    gic = Arm_GIC.create(arch, dtb)

    assert gic.version == Arm_GIC.Version.V2
    assert gic.cpu_paddr == 0x2000
    assert gic.vcpu_paddr == 0x4000
    assert gic.vcpu_size == 0x40
    assert gic.has_mmio_cpu_interface() is True


def test_arm_gic_create_v3():
    arch = MagicMock()
    dtb = MagicMock()
    node = MagicMock()
    dtb.nodes = {0: node}
    dtb.get_compatible.return_value = ["arm,gic-v3"]
    dtb.get_node_regs.return_value = [
        (0x0, 0x0),
        (0x0, 0x0),
        (0xC000, 0x10),
        (0x0, 0x0),
        (0xE000, 0x40),
    ]
    dtb.get_reg_paddr.side_effect = lambda a, n, addr: addr

    gic = Arm_GIC.create(arch, dtb)

    assert gic.version == Arm_GIC.Version.V3
    assert gic.cpu_paddr == 0xC000
    assert gic.vcpu_paddr == 0xE000
    assert gic.vcpu_size == 0x40


def test_arm_gic_create_cpu_only_no_vcpu():
    arch = MagicMock()
    dtb = MagicMock()
    node = MagicMock()
    dtb.nodes = {0: node}
    dtb.get_compatible.return_value = ["arm,gic-400"]
    dtb.get_node_regs.return_value = [(0x1000, 0x10), (0x2000, 0x20)]
    dtb.get_reg_paddr.side_effect = lambda a, n, addr: addr

    gic = Arm_GIC.create(arch, dtb)

    assert gic.cpu_paddr == 0x2000
    assert gic.vcpu_paddr is None
    assert gic.vcpu_size is None


def test_arm_gic_create_unknown_version_raises():
    arch = MagicMock()
    dtb = MagicMock()
    node = MagicMock()
    dtb.nodes = {0: node}
    dtb.get_compatible.side_effect = [["arm,gic-v2"], ["weird,thing"]]
    with pytest.raises(RuntimeError, match="Unable to determine GIC version"):
        Arm_GIC.create(arch, dtb)


def test_init_stores_path_and_fdt():
    f = MagicMock()
    f.next_node.return_value = (0, 0)
    f.get_path.side_effect = FakeFdtException()
    b = _construct_blob(f)
    assert b.file_path == "dummy.dtb"
    assert b.fdt is f
    assert b.nodes == {}


def test_enumerate_nodes_populates():
    f = MagicMock()
    f.next_node.side_effect = [(0, 0), (1, 0), (2, 0), (99, 0)]

    def get_path(off):
        paths = {0: "/", 1: "/foo", 2: "/bar"}
        if off not in paths:
            raise FakeFdtException()
        return paths[off]

    f.get_path.side_effect = get_path
    b = _construct_blob(f)
    assert b.nodes == {
        0: DTBNode(0, "/"),
        1: DTBNode(1, "/foo"),
        2: DTBNode(2, "/bar"),
    }


def test_get_compatible_returns_strings(blob, fdt):
    fdt.hasprop.return_value = True
    fdt.getprop.return_value = b"arm,gic-400\x00arm,gic-v2\x00"
    assert blob.get_compatible(DTBNode(5, "/gic")) == ["arm,gic-400", "arm,gic-v2"]


def test_get_compatible_no_prop_returns_empty(blob, fdt):
    fdt.hasprop.return_value = False
    assert blob.get_compatible(DTBNode(5, "/x")) == []


def test_get_nodes_by_compatible(blob):
    n0 = DTBNode(0, "/a")
    n1 = DTBNode(1, "/b")
    n2 = DTBNode(2, "/c")
    blob.nodes = {0: n0, 1: n1, 2: n2}
    blob.get_compatible = MagicMock(
        side_effect=lambda n: ["match"] if n in (n0, n2) else ["other"]
    )
    assert blob.get_nodes_by_compatible("match") == [n0, n2]


def test_get_node_by_path_adds_leading_slash(blob, fdt):
    fdt.path_offset.return_value = 42
    node = blob.get_node_by_path("soc/timer")
    assert node == DTBNode(42, "/soc/timer")
    fdt.path_offset.assert_called_with("/soc/timer")


def test_get_node_by_path_existing_slash(blob, fdt):
    fdt.path_offset.return_value = 7
    assert blob.get_node_by_path("/already") == DTBNode(7, "/already")


def test_get_node_prop(blob, fdt):
    fdt.getprop.return_value = b"data"
    assert blob.get_node_prop(DTBNode(3, "/x"), "foo") == b"data"
    fdt.getprop.assert_called_with(3, "foo")


def test_get_node_parent(blob, fdt):
    parent = DTBNode(1, "/parent")
    blob.nodes = {1: parent}
    fdt.parent_offset.return_value = 1
    assert blob.get_node_parent(DTBNode(2, "/child")) is parent


_RAW_CELLS = DeviceTreeBlob.get_size_and_addr_cells


def test_size_and_addr_cells_defaults(blob, fdt):
    fdt.hasprop.return_value = False
    assert _RAW_CELLS(blob, DTBNode(0, "/")) == (1, 2)


def test_size_and_addr_cells_with_props(blob, fdt):
    fdt.hasprop.return_value = True
    size_prop = MagicMock()
    size_prop.as_uint32.return_value = 4
    addr_prop = MagicMock()
    addr_prop.as_uint32.return_value = 3
    fdt.getprop.side_effect = lambda off, name: size_prop if name == "#size-cells" else addr_prop
    assert _RAW_CELLS(blob, DTBNode(0, "/")) == (4, 3)


def test_size_and_addr_cells_ignores_address_cells_without_size_cells(blob, fdt):
    # The second branch erroneously gates on "#size-cells" instead of
    # "#address-cells", so a node with only #address-cells falls back to the
    # default addr-cells of 2.
    fdt.hasprop.side_effect = lambda off, name: name == "#address-cells"
    assert _RAW_CELLS(blob, DTBNode(0, "/")) == (1, 2)


def test_get_node_regs_single_entry(blob, fdt):
    node = DTBNode(10, "/soc/uart")
    blob.get_node_parent = MagicMock(return_value=DTBNode(2, "/soc"))
    blob.get_size_and_addr_cells = MagicMock(return_value=(1, 2))
    fdt.getprop.return_value = struct.pack(">3I", 0x0, 0x1000, 0x100)
    assert blob.get_node_regs(node) == [(0x1000, 0x100)]


def test_get_node_regs_multiple_entries_64bit(blob, fdt):
    node = DTBNode(10, "/soc/uart")
    blob.get_node_parent = MagicMock(return_value=DTBNode(2, "/soc"))
    blob.get_size_and_addr_cells = MagicMock(return_value=(1, 2))
    fdt.getprop.return_value = struct.pack(">6I", 0, 0x1000, 0x100, 0x1, 0x0, 0x200)
    assert blob.get_node_regs(node) == [(0x1000, 0x100), (0x100000000, 0x200)]


def test_get_node_regs_misaligned_raises(blob, fdt):
    node = DTBNode(10, "/soc/uart")
    blob.get_node_parent = MagicMock(return_value=DTBNode(2, "/soc"))
    blob.get_size_and_addr_cells = MagicMock(return_value=(1, 2))
    fdt.getprop.return_value = b"\x00\x00\x00"
    with pytest.raises(RuntimeError, match="32 bit aligned"):
        blob.get_node_regs(node)


def test_get_node_irqs(blob, fdt):
    fdt.getprop.return_value = struct.pack(">3I", 0, 5, 4)
    assert blob.get_node_irqs(DTBNode(7, "/x")) == (0, 5, 4)


def test_get_parsed_irqs_arm_groups_by_three(blob, fdt):
    arch = MagicMock()
    arch.is_arm.return_value = True
    arch.is_riscv.return_value = False
    fdt.getprop.return_value = struct.pack(">6I", 0, 5, 1, 1, 7, 4)
    with patch.object(dtb_module, "_parse_irq", side_effect=lambda a, c: ("irq", tuple(c))):
        result = blob.get_parsed_irqs(DTBNode(7, "/x"), arch)
    assert result == [("irq", (0, 5, 1)), ("irq", (1, 7, 4))]


def test_get_parsed_irqs_riscv_groups_by_one(blob, fdt):
    arch = MagicMock()
    arch.is_arm.return_value = False
    arch.is_riscv.return_value = True
    fdt.getprop.return_value = struct.pack(">2I", 5, 7)
    with patch.object(dtb_module, "_parse_irq", side_effect=lambda a, c: ("irq", tuple(c))):
        result = blob.get_parsed_irqs(DTBNode(7, "/x"), arch)
    assert result == [("irq", (5,)), ("irq", (7,))]


def test_get_parsed_irqs_misaligned_raises(blob, fdt):
    arch = MagicMock()
    arch.is_arm.return_value = True
    arch.is_riscv.return_value = False
    fdt.getprop.return_value = struct.pack(">2I", 0, 5)
    with pytest.raises(RuntimeError, match="not a multiple"):
        blob.get_parsed_irqs(DTBNode(7, "/x"), arch)


def test_get_parsed_irqs_unsupported_arch_raises(blob, fdt):
    arch = MagicMock()
    arch.is_arm.return_value = False
    arch.is_riscv.return_value = False
    fdt.getprop.return_value = struct.pack(">1I", 5)
    with pytest.raises(RuntimeError, match="Unsupported architecture"):
        blob.get_parsed_irqs(DTBNode(7, "/x"), arch)


def test_get_reg_paddr_alignment_only(blob):
    arch = MagicMock()
    arch.default_page_size.return_value = 0x1000
    blob.get_node_parent = MagicMock(side_effect=KeyError)
    assert blob.get_reg_paddr(arch, DTBNode(5, "/x"), 0x1234) == 0x1000


def test_get_reg_paddr_empty_ranges_is_passthrough(blob, fdt):
    arch = MagicMock()
    arch.default_page_size.return_value = 0x1000
    node = DTBNode(10, "/soc/dev")
    parent = DTBNode(5, "/soc")

    def parent_of(n):
        if n is node:
            return parent
        raise KeyError

    blob.get_node_parent = MagicMock(side_effect=parent_of)
    fdt.hasprop.side_effect = lambda off, name: off == 5 and name == "ranges"
    fdt.getprop.return_value = b""
    assert blob.get_reg_paddr(arch, node, 0x3456) == 0x3000


def test_get_reg_paddr_translates_through_ranges(blob, fdt):
    arch = MagicMock()
    arch.default_page_size.return_value = 0x1000
    node = DTBNode(10, "/soc/bus/dev")
    parent = DTBNode(5, "/soc/bus")
    grandparent = DTBNode(2, "/soc")

    def parent_of(n):
        if n is node:
            return parent
        if n is parent:
            return grandparent
        raise KeyError

    blob.get_node_parent = MagicMock(side_effect=parent_of)
    blob.get_size_and_addr_cells = MagicMock(return_value=(1, 1))
    fdt.hasprop.side_effect = lambda off, name: off == 5 and name == "ranges"
    ranges_raw = struct.pack(">3I", 0x1000, 0x80000000, 0x2000)
    fdt.getprop.side_effect = (
        lambda off, name: ranges_raw if (off == 5 and name == "ranges") else b""
    )
    assert blob.get_reg_paddr(arch, node, 0x2000) == 0x80001000
