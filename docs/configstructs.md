<!--
    Copyright 2026, UNSW

    SPDX-License-Identifier: BSD-2-Clause
-->


# Config structs

Config structs are a representation of a structure in a compiled program that we will pack with configuration data. Acacia will attempt to convert
Python values in the `ConfigStruct` to C values for all [supported types](#types).

Acacia will throw an error if any of the following conditions are true:
* Your config struct has fields that are not in the C code.
* Your config struct is missing fields that are not in the C code.
* Your config struct is empty, but isn't marked as `empty`.
* The Python type of a field is unsupported (e.g. `defaultdict`).
* The Python value of a field doesn't fit in the container, e.g. packing `-1` into an `unsigned` container or a `List[int]` has too many fields to fit into a C array.
* An integer value is too large for the bit width of the C type.


All `ConfigStruct`s must have:
* A `type_name` denoting the C type of this, e.g. `sddf_timer_client_config_t`.
* A list of `fields` - name-value pairs matching the layout of a struct. E.g.
  "queue_vaddr" : 0x20000000. Names must exactly match the name of the field in
  C and the value should be an appropriate Python type. All fields in the real
  struct should be present, otherwise an error will be thrown.

If a `ConfigStruct` is at the top level, i.e. it is corresponding to a symbol to patch
as opposed to being a `ConfigStruct` nested inside another `ConfigStruct`, it must define:
* `target_file`: the name of the ELF file this will be patched into.
* `section_name`: The name of the ELF section this belongs to.

In the event that a ConfigStruct is unused, or we want to zero-fill a struct inside of another
`ConfigStruct`, you may set the `empty` field to True. This will cause Acacia to skip trying
to populate it while suppressing the "missing field" error that would normally appear if you
ignore fields of a struct.

## Types

Acacia is able to serialise the following Python objects if they are a field:
* `int` - a number. Can be packed into a signed or unsigned container in C.
* `str` - a single character or string of characters.
* `bytes` or `bytearray` - an array of bytes.
* `ConfigStruct` - any other ConfigStruct. Can be `empty=True` if you want to mark a field as unused.
* Lists or tuples of any of the above (multidimensional currently unsupported).

NOTE: if packing into a `char` array, Acacia will enforce that the final byte is a null terminator.
