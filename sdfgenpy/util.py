# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
from functools import wraps
from ctypes import (
    c_void_p, c_uint64, c_uint32, c_uint16, c_uint8, c_char, c_byte, c_ubyte,
    c_uint, c_ulong, c_ulonglong, c_ushort, Array, Structure, sizeof)
from typing import Union, Optional, Type

def parameterised_decorator(d):
    """
    Metadecorator enabling @decorator(arg) syntax.
    Transforms a function signature (f, *args, **kwargs) into
    decorator factory syntax (*args, **kwargs) -> (f -> result).
    """
    @wraps(d)
    def factory(*args, **kwargs):
        @wraps(d)
        def decorator(f):
            return d(f, *args, **kwargs)
        return decorator
    return factory

# Abstract fixed-width containers. These couple
# values to their types but have no explicit
# endianness until required. This lets subsystems
# define their structs without needing to know the
# target system endianness.

UNSIGNED_TYPES = [
    c_void_p, c_uint64, c_uint32, c_uint16, c_uint8, c_char, c_byte, c_ubyte,
    c_uint, c_ulong, c_ulonglong, c_ushort
]

class AbstractCType:
    def __init__(self,
                 value: int,
                 ctype: Type):
        self.value = value
        self.ctype = ctype

        # Sanity: check for signedness collision as ctypes will let you
        # initialise a type with literally ANYTHING.
        if ctype in UNSIGNED_TYPES and value < 0:
            raise RuntimeWarning(f"Initialising {ctype} value with signed "
                                 f"value={value}!")

        # TODO: check value fits in bit width. This is a vector for bugs as ctypes
        # will once again let you put garbage into the initialiser.

    def endiannise(self, big_endian=False):
        """
        Return this value as a raw ctypes of a specified
        endianness.
        """
        if big_endian:
            return self.ctype.__ctype_be__(self.value)
        else:
            return self.ctype.__ctype_le__(self.value)
#
# class AbstractCFixedArray:
#     def __init__(self,
#                  width: int,
