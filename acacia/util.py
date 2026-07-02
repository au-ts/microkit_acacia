# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
from functools import wraps
from ctypes import (
    c_void_p,
    c_uint64,
    c_uint32,
    c_uint16,
    c_uint8,
    c_char,
    c_byte,
    c_ubyte,
    c_uint,
    c_ulong,
    c_ulonglong,
    c_ushort,
    Array,
    Structure,
    sizeof,
)
from typing import Union, Optional, Type


def ctz(x: int, bits: int = 64):
    # invariant: input is sized to fit in a word of size `bits`
    if x == 0:
        return bits
    return (x & -x).bit_length() - 1
