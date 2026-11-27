# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
from collections.abc import Iterable, Sized
from typing import Any, Dict, List, Optional, Tuple, Union


class CType:
    """
    Class encapsulating a "tag entry" (or debugging information entry) found in
    a binary file's llvm-dwarfdump output. Tag entries contain information about
    the source program, including the defined types. The type information
    captured allows Acacia to serialise Python configuration data into the
    format expected by the source program.

    Each CType contains:
    * a dictionary containing the CType of each tag entry found in the source
    elf file, mapping the entry's ID to the corresponding CType
    * a dictionary of the tag's listed attributes, with the string of the
    attribute's name as the key
    * a list of the IDs of tags defined within the scope of this CType, or child
    CTypes

    Examples of such tag entries used by this module include an array entry with
    a subrange child:

    0x0000003d:   DW_TAG_array_type
                    DW_AT_type	(0x00000049 "char")

    0x00000042:     DW_TAG_subrange_type
                      DW_AT_type	(0x0000004d "__ARRAY_SIZE_TYPE__")
                      DW_AT_count	(0x37)

    0x00000048:     NULL

    or a structure type entry with member type children:

    0x000000d8:   DW_TAG_structure_type
                    DW_AT_name	("region_resource") DW_AT_byte_size (0x10)
                    DW_AT_decl_file	("/sDDF/include/sddf/resources/common.h")
                    DW_AT_decl_line	(11)

    0x000000dd:     DW_TAG_member
                      DW_AT_name	("vaddr")
                      DW_AT_type	(0x000000f0 "void *")
                      DW_AT_decl_file	("/sDDF/include/sddf/resources/common.h")
                      DW_AT_decl_line	(12)
                      DW_AT_data_member_location	(0x00)

    0x000000e6:     DW_TAG_member
                      DW_AT_name	("size")
                      DW_AT_type	(0x000000f1 "uint64_t")
                      DW_AT_decl_file	("/sDDF/include/sddf/resources/common.h")
                      DW_AT_decl_line	(13)
                      DW_AT_data_member_location	(0x08)

    0x000000ef:     NULL
    """

    def __init__(self, ctypes: Dict[int, CType], tag_type: str):
        """
        :param ctypes: Dictionary containing all CTypes found in the source elf
            file, mapping ID to CType
        :param tag_type: Type of the tag entry, encoded as the string that
            follows 'DW_TAG_'. Examples include 'array_type', 'subrange_type',
            'structure_type', or 'member'
        """
        self.ctypes = ctypes
        self.tag_type = tag_type
        self.attributes: Dict[str, str] = dict()
        self.children: List[int] = list()

    @property
    def name(self) -> Optional[str]:
        """
        Returns the name of the CType if defined, else None.
        """
        if "name" in self.attributes:
            # Raw line: DW_AT_name	("usize"), self.attributes["name"] = '"usize"'
            return self.attributes["name"].strip('"')
        return None

    @property
    def base_type_id(self) -> Optional[int]:
        """
        Returns the ID of the CType's base type if defined, else None. This
        field is used in tags where the type of the entry is defined elsewhere,
        like typedef types or member types.
        """
        if "type" in self.attributes:
            # Raw line: DW_AT_type	(0x00000068 "usize"), self.attributes["type"] = '0x00000068 "usize"'
            return int(self.attributes["type"][2:10], base=16)
        return None

    @property
    def count(self) -> Optional[int]:
        """
        Returns the count or number of entries of a CType if defined, else
        None. This field is used in subrange types, which are children of array
        types.
        """
        if "count" in self.attributes:
            # Raw line: DW_AT_count	(0x01), self.attributes["count"] = '0x01'
            return int(self.attributes["count"][2:], base=16)
        if "upper_bound" in self.attributes:
            # Raw line: DW_AT_upper_bound   (0x14), self.attributes["upper_bound"] = '0x14'
            # upper bound is the last valid index in an array
            return int(self.attributes["upper_bound"][2:], base=16) + 1
        return None

    @property
    def byte_size(self) -> Optional[int]:
        """
        Returns the size of the CType in bytes if defined, else None.
        """
        if "byte_size" in self.attributes:
            # Raw line: DW_AT_byte_size	(0x08), self.attributes["byte_size"] = '0x08'
            return int(self.attributes["byte_size"][2:], base=16)
        return None

    @property
    def data_member_location(self) -> Optional[int]:
        """
        Returns the data member location or byte offset from the start of the
        parent CType if defined, else None. Used in member types, which are
        child types of structure types or union types.
        """
        if "data_member_location" in self.attributes:
            # Raw line: DW_AT_data_member_location  (0x00), self.attributes["data_member_location"] = '0x00'
            return int(self.attributes["data_member_location"][2:], base=16)
        return None

    @property
    def encoding(self) -> Optional[str]:
        """
        Returns how the CType is encoded if defined, else None. Used in
        base_types.
        """
        if "encoding" in self.attributes:
            # Raw line: DW_AT_encoding	(DW_ATE_unsigned), self.attributes["encoding"] = 'DW_ATE_unsigned'
            return self.attributes["encoding"].lstrip("DW_ATE_")
        return None

    @property
    def declaration(self) -> bool:
        """
        Returns whether the CType is simply a declaration and not defined.
        """
        return (
            "declaration" in self.attributes
            # Raw line: DW_AT_declaration (true), self.attributes["declaration"] = 'true'
            and self.attributes["declaration"] == "true"
        )

    def calc_byte_size(self) -> int:
        """
        Calculates the byte size of a CType. If byte size is defined, it is
        returned directly. If CType is a pointer type, 8 is returned. If CType
        is an array type, the byte size is calculated from the number of entries
        and the size of it's entries. If byte size is not possible to calculate,
        an exception is raised.
        """
        if self.byte_size:
            return self.byte_size
        elif self.tag_type == "pointer_type":
            return 8
        elif self.tag_type == "array_type":
            entry_type = self.find_base_type(True)
            array_counts = self.find_array_count()

            if len(array_counts) != 1:
                raise ValueError(
                    f"Acacia does not support config structs with multi-dimensional arrays. Array type '{self}' has dimensions '{array_counts}'"
                )
            elif array_counts[0] is None:
                raise ValueError(
                    f"Acacia does not support config structs including arrays with no specified number of entries. Array type '{self}'"
                )
            elif array_counts[0] == 0:
                raise ValueError(
                    f"Acacia does not support config structs including arrays with zero entries. Array type '{self}'"
                )

            num_entries = array_counts[0]
            return num_entries * entry_type.calc_byte_size()

        raise ValueError(f"Could not calculate byte size of type {self}")

    def __eq__(self, other: object):
        """
        Checks whether another object is equal to a CType. Equality requires
        that the object is a CType with equal attributes and children, excluding
        the ID of the base type (equality of the CTypes corresponding to the
        base type ID are recursively checked). Types with identical shapes can
        have different type IDs, thus this field can produce false inequality
        for the purposes of serialising types.
        """
        if not isinstance(other, CType):
            return False

        if self.tag_type != other.tag_type:
            return False

        keys = [k for k in self.attributes if k != "type"]
        if self.attributes.keys() != other.attributes.keys() or any(
            self.attributes[k] != other.attributes[k] for k in keys
        ):
            return False

        if (
            self.base_type_id is not None
            and other.base_type_id is not None
            and self.ctypes[self.base_type_id] != other.ctypes[other.base_type_id]
        ):
            return False

        return list(self.ctypes[child] for child in self.children) == list(
            other.ctypes[child] for child in other.children
        )

    def __repr__(self):
        join_string = "\n    "
        repr_string = f"{self.tag_type}: {self.name},\nAttributes:\n    {join_string.join(f'{k}: {v}' for k, v in self.attributes.items())}\n"

        if len(self.children):
            repr_string += f"Children:\n    {join_string.join(f'{child_id}: {self.ctypes[child_id]}' for child_id in self.children)}\n"

        return repr_string

    def find_base_type(self, resolve_array_type: bool) -> CType:
        """
        Finds the base CType of a given CType using the base type's ID. This
        function does not resolve the base type of pointer types as Acacia
        treats all pointer types as 8 byte unsigned encodings. `self` is
        returned if there is no base type, `self` is a pointer type or `self` is
        an array type, and array types are not required to be resolved.

        :param resolve_array_type: Whether array types should be resolved to
            their entry type or returned without modification
        """
        if (
            not self.base_type_id
            or (not resolve_array_type and self.tag_type == "array_type")
            or self.tag_type == "pointer_type"
        ):
            return self

        base_type = self.ctypes[self.base_type_id]
        if not base_type:
            raise ValueError(
                f"Could not find base type ({self.base_type_id}) of CType {self}"
            )

        # Only resolve to the original type's entry type, do not resolve
        # result's entry type
        return base_type.find_base_type(False)

    def find_array_count(self) -> List[Optional[int]]:
        """
        Finds the number of entries in each dimension of an array type by examining
        each subrange type. E.g. array[6][8] will return [6, 8].
        """
        if self.tag_type != "array_type":
            raise ValueError(f"Non array types do not support array counts {self}")

        subrange_counts = list()
        for subrange_type in [self.ctypes[child_id] for child_id in self.children]:
            if subrange_type.tag_type != "subrange_type":
                raise ValueError(
                    f"ConfigStruct module does not support array types with non-subrange child types {self}"
                )

            subrange_counts.append(subrange_type.count)

        return subrange_counts


def find_ctype_by_name(ctypes: Dict[int, CType], name: str) -> Optional[CType]:
    """
    Recursively searches for CTypes of a given name. Only considers matches
    which correspond to a 'type' or 'typedef' entry. If multiple matches are
    found, equality is checked. If valid matches are found which are not equal,
    an exception is raised as Acacia is unable to determine which encoding the
    user intends to serialise to.

    :param ctypes: Dictionary of type IDs to CTypes to search
    :param name: Name of the CType to find
    """
    matches = list()
    for entry in ctypes.values():
        if entry.name == name:
            matches.append(entry)

    match = None
    for next_match in matches:
        if (
            not next_match.tag_type.endswith("type")
            and next_match.tag_type != "typedef"
        ) or next_match.declaration:
            continue
        if match is None:
            match = next_match
            continue
        elif match != next_match:
            raise ValueError(
                f"Found two distinct CTypes with the same name ({name}), {match} {next_match}"
            )

    return match


# The following functions parse dwarf dump output relying on:
# 1. Indentation, meaning:
#   - The amount of whitespace between IDs and the tag entry declaration
#   - The amount of whitespace preceding an attribute
# Dwarf dump output uses indentation to indicate whether a subsequent child
# entry is within the scope of the preceding entry.
# 2. Tag entries beginning with an ID followed by "DW_TAG_*".
# 3. Tag entry's attributes starting on the line immediately after the tag
#    entry, and terminating with a newline.
# 4. Attributes having the format ` `+DW_AT_* (...)

# Smallest whitespace between ID and tag name: 0x000000a9: DW_TAG_compile_unit
BASE_TAG_INDENT = 1

# Smallest whitespace before start of tag's attributes:              DW_AT_producer	("...")
BASE_ATTR_INDENT = 14

# Increase in whitespace per depth level (2nd depth level example): 0x000000c8:   DW_TAG_namespace
DEPTH_MULTIPLIER = 2


def eat_attributes(
    lines: List[str], start_idx: int, depth: int, ctype_attrs: Dict[str, str]
) -> int:
    """
    Extracts the attributes of a tag entry. Assumes that an entry's attributes
    are listed contiguously after the entry declaration, terminating with an
    empty newline.

    :param lines: Lines of dwarfdump output
    :param start_idx: Current line to search from
    :param depth: Recursive depth of the function, or the current number of
        parent CTypes. Required to determine the expected amount of whitespace
        prior to each attribute
    :param ctype_attrs: The corresponding CType's attribute dictionary to
        collect attributes into. Attributes are inserted into the dictionary
        with the attribute name as the key, and the value without the enclosing
        brackets as the value

    :return: The next line number after the empty attribute terminating line
    """
    while start_idx < len(lines):
        attribute_match = re.match(r"^( +)DW_AT_([^\s]+)\t(.*)", lines[start_idx])
        if attribute_match:
            indent = len(attribute_match.group(1))
            if indent != depth * DEPTH_MULTIPLIER + BASE_ATTR_INDENT:
                raise ValueError(
                    f"Expected tag attribute to be indented with {depth * DEPTH_MULTIPLIER + BASE_ATTR_INDENT} spaces, found {indent} spaces"
                )

            attribute_value = attribute_match.group(3)
            start_idx += 1
            # The following lines handle multi-line attributes, like
            # DW_AT_location	(indexed (0x3) loclist = 0x00002f0a:
            #    [0x0000000000205dc0, 0x0000000000205ddc): DW_OP_reg11 W11
            #    [0x0000000000205e98, 0x0000000000205eb4): DW_OP_reg12 W12
            #    [0x0000000000205f64, 0x0000000000205f80): DW_OP_reg11 W11)
            while start_idx < len(lines) and len(lines[start_idx]):
                if re.match(r"^( +)DW_AT_([^\s]+)\t(.*)", lines[start_idx]):
                    break

                multi_line_value_match = re.match(r"^ +([^ ].*)", lines[start_idx])
                if not multi_line_value_match:
                    raise ValueError(
                        f"Expected a multi-line attribute (line {start_idx}), found {lines[start_idx]}"
                    )

                attribute_value += multi_line_value_match.group(1)
                start_idx += 1

            ctype_attrs[attribute_match.group(2)] = attribute_value[1:-1]

        else:
            if not len(lines[start_idx]) == 0:
                raise ValueError(
                    f"Expected a tag attribute or empty line (line {start_idx}), found {lines[start_idx]}"
                )
            return start_idx + 1

    return start_idx


def eat_tag(
    lines: List[str],
    start_idx: int,
    depth: int,
    ctypes: Dict[int, CType],
    child_list: List[int],
) -> int:
    """
    Extracts each tag entry contained within 'lines', creating a dictionary of
    tag IDs to extracted CTypes. This function is called recursively, so each
    time a new indentation level is found, the function will be called again.

    :param lines: Lines of dwarfdump output
    :param start_idx: Current line to search from
    :param depth: Recursive depth of the function, or the current number of
        parent CTypes
    :param ctypes: The dictionary to collect CTypes into.
    :param child_list: The current list of children IDs to collect IDs into.
        When a greater indentation or depth is reached, eat_tag will be called
        recursively using the 'children' list of the parent CType, or the CType
        whose scope the tag entry belongs to.

    :return: Next line number to be parsed
    """
    prev_id = 0
    while start_idx < len(lines):
        tag_match = re.match(r"^0x([0-9a-f]{8}):( +)DW_TAG_(.+)", lines[start_idx])
        if tag_match:
            tag_depth = (len(tag_match.group(2)) - BASE_TAG_INDENT) // DEPTH_MULTIPLIER
            if tag_depth == depth:
                prev_id = int(tag_match.group(1), base=16)
                ctypes[prev_id] = CType(ctypes, tag_match.group(3))
                child_list.append(prev_id)
                start_idx = eat_attributes(
                    lines, start_idx + 1, tag_depth, ctypes[prev_id].attributes
                )
            elif tag_depth < depth:
                # We are no longer in scope
                return start_idx
            elif tag_depth == depth + 1:
                # This tag is in the scope of last entry
                start_idx = eat_tag(
                    lines, start_idx, depth + 1, ctypes, ctypes[prev_id].children
                )
            else:
                raise ValueError(
                    f"Indentation level on line {start_idx} increased by more than one, current depth: {depth}, depth found: {tag_depth}"
                )
        else:
            start_idx += 1

    return start_idx


class ConfigStruct:
    """
    A representation of a structure in a compiled program that we will pack with
    configuration data.

    This class provides a template for creating a configuration struct which will
    be serialised into a matching C struct found in a component's ELF file.

    All `ConfigStruct`s must have:
    * A `type_name` denoting the C type of this, e.g. `sddf_timer_client_config_t`.
    * A list of `fields` - name-value pairs matching the layout of a struct. E.g.
      "queue_vaddr" : 0x20000000. Names must exactly match the name of the field in
      C and the value should be an appropriate Python type. All fields in the real
      struct should be present, otherwise an error will be thrown.

    E.g.
    * a string -> character array
    * list of `int` -> list of integers of some C type (automatically checks if signed!)
    * a bytearray -> list of integers of some C type
    * Another `ConfigStruct` -> a struct.

    If this `ConfigStruct` is at the top level, i.e. it is corresponding to a symbol to patch
    as opposed to being a `ConfigStruct` nested inside another `ConfigStruct`, it must define:
    * `target_file`: the name of the ELF file this will be patched into.
    * `section_name`: The name of the ELF section this belongs to.
       NOTE: this currently is unused! https://github.com/au-ts/microkit_acacia/issues/48

    In the event that a ConfigStruct is unused, or we want to zero-fill a struct inside of another
    `ConfigStruct`, you may set the `empty` field to True. This will cause Acacia to skip trying
    to populate it while suppressing the "missing field" error that would normally appear if you
    ignore fields of a struct.
    """

    def __init__(
        self,
        fields: Dict[str, Any],
        type_name: Optional[str] = None,
        section_name: Optional[pathlib.Path] = None,
        target_file: Optional[pathlib.Path] = None,
        empty: bool = False,
    ):
        """
        :param fields: dictionary of field names -> values. Can be:
            * Another ConfigStruct
            * Any int-like value
            * Any string or bytes
            * A list of values
        :param type_name: type of struct in C
        :param section_name: name of section to patch config struct into
        :param target_file: ELF file this will be patched into
        """
        self.empty = empty
        if self.empty and len(fields):
            raise ValueError("Empty config structs cannot have fields!")

        self.fields = fields
        self.type_name = type_name
        self.section_name = section_name
        self.target_file = target_file

    def __repr__(self):
        return f"<ConfigStruct {self.type_name} {self.fields}>"


class ConfigStructResolver:
    """
    This class records all configuration structs of a system. As structs are
    added to this class, their target files are dwarf dumped and parsed, and all
    CTypes they contain are collected into a dictionary.

    Once all structs of the system are added, they are serialised one-by-one
    based on the memory layout of their types derived from the DWARF symbols in
    the ELF file. Each serialised struct is then written to a file in the build
    directory.

    This is an internal class for Acacia and is not used by end users.
    """

    def __init__(
        self,
        build_dir: pathlib.Path,
        endian="little",
        dwarfdump_name: str = "llvm-dwarfdump",
    ):
        """
        :param build_dir: name of the build directory, used for emitting serialised
            structs
        :param endian: endianness of encoding
        :param dwarfdump_name: name of dwarf dump command
        """
        if endian != "little":
            raise NotImplementedError("Big endian is not currently supported!")

        self.build_dir = build_dir
        self.dwarfdump_name = dwarfdump_name
        self.files: Dict[pathlib.Path, Dict[int, CType]] = dict()
        self.config_structs: List[ConfigStruct] = []

        try:
            subprocess.run([self.dwarfdump_name, "--version"])
        except FileNotFoundError as e:
            raise RuntimeError(
                f"No LLVM DwarfDump! Make sure {self.dwarfdump_name} is on your PATH"
            ) from e

    def add_struct(self, s: ConfigStruct):
        """
        Add a configuration struct to the resolver.
        """
        try:
            if s.section_name is None:
                raise ValueError("Cannot emit a config struct without a section name!")
            if s.target_file is None:
                raise ValueError(
                    "Cannot patch in a config struct without a target file!"
                )
            if s.type_name is None:
                raise ValueError("Cannot patch in a config struct without a type name!")

            if s.target_file not in self.files:
                self.files[s.target_file] = self.resolve_target_file(s.target_file)
        except Exception as e:
            raise RuntimeError(f"Failed to add config struct {s}!") from e

        self.config_structs.append(s)

    def add_structs(self, lst: List[ConfigStruct]):
        """
        Add a list of configuration structs to the resolver.
        """
        for s in lst:
            self.add_struct(s)

    def resolve_target_file(self, target_file: pathlib.Path) -> Dict[int, CType]:
        """
        Dwarf dump a target file, parse the output and collect all CTypes into a dictionary.
        """
        try:
            output = subprocess.run(
                [self.dwarfdump_name, target_file],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to eat DWARF from {target_file}! Does file exist?"
            ) from e

        type_collector: Dict[int, CType] = dict()
        eat_tag(output.stdout.splitlines(), 0, 0, type_collector, [])

        return type_collector

    def _flatten_and_write(
        self, ctypes: Dict[int, CType], user_value: Any, type_match: CType
    ) -> bytes:
        """
        Returns the serialised bytes of the C type with value user_value. Used
        to create serialised configuration structs for Acacia components.

        This function is recursive. If the C type is an array or struct type,
        the function will call itself on each of the entries/members, until
        eventually a "base" type or "pointer" type is reached. The user value
        will then be serialised into bytes of the base C type.

        The bytes of each member are then placed at the member's offset within
        the struct or array. Members are filled from offset 0 onwards.
        Zero-filled padding is added between members if the member's bytes do
        not reach the next offset.

        We only support pointer types for 64 bit architectures. Pointers are
        translated into 8 byte unsigned C types.
        """

        # Check for an empty ConfigStruct - if so, zero fill
        if isinstance(user_value, ConfigStruct) and user_value.empty:
            if type_match.byte_size and type_match.tag_type == "structure_type":
                return bytes(type_match.byte_size)
            else:
                raise ValueError(
                    f"User provided empty ConfigStruct ({user_value}) for non-structure type ({type_match})"
                )

        match type_match.tag_type:
            case "pointer_type":
                try:
                    return user_value.to_bytes(type_match.calc_byte_size(), "little")
                except Exception as e:
                    raise ValueError(
                        f"Could not create C pointer type from value '{user_value}'"
                    ) from e

            case "base_type":
                try:
                    if isinstance(user_value, str) or isinstance(user_value, bytes):
                        if type_match.byte_size != 1 or len(user_value) != 1:
                            raise ValueError(
                                f"Strings and bytes are only supported for single byte sized encoding, not encoding '{type_match.encoding}' with byte size '{type_match.byte_size}'"
                            )

                        if isinstance(user_value, str):
                            user_byte_value = user_value.encode()
                            if len(user_byte_value) != 1:
                                raise ValueError(
                                    f"Length 1 string provided `{user_value}` encoded to len={len(user_byte_value)} bytes, should have byte length 1"
                                )
                            return user_byte_value
                        elif isinstance(user_value, bytes):
                            return user_value

                    elif type_match.encoding in (
                        "unsigned",
                        "signed",
                        "boolean",
                        "unsigned_char",
                        "signed_char",
                    ):
                        assert type_match.byte_size
                        return user_value.to_bytes(
                            type_match.byte_size,
                            "little",
                            signed=(
                                type_match.encoding == "signed"
                                or type_match.encoding == "signed_char"
                            ),
                        )
                    else:
                        raise ValueError(
                            f"Only char, int and bool encodings are supported, matching encoding is '{type_match.encoding}'"
                        )
                except ValueError as e:
                    raise e
                except Exception as e:
                    raise ValueError(
                        f"User provided value '{user_value!r}' which cannot be encoded into base type '{type_match}'"
                    ) from e

            case "array_type":
                entry_type = type_match.find_base_type(True)
                array_counts = type_match.find_array_count()

                if len(array_counts) != 1:
                    raise ValueError(
                        f"Acacia does not support config structs with multi-dimensional arrays. Array type '{type_match}' has dimensions '{array_counts}'"
                    )
                elif array_counts[0] is None:
                    raise ValueError(
                        f"Acacia does not support config structs including arrays with no specified number of entries. Array type '{type_match}'"
                    )
                elif array_counts[0] == 0:
                    raise ValueError(
                        f"Acacia does not support config structs including arrays with zero entries. Array type '{type_match}'"
                    )
                num_entries = array_counts[0]

                if (
                    not (
                        isinstance(user_value, list)
                        or isinstance(user_value, tuple)
                        or isinstance(user_value, str)
                        or isinstance(user_value, bytes)
                        or isinstance(user_value, bytearray)
                    )
                    or len(user_value) > num_entries
                ):
                    raise ValueError(
                        f"Can't fill an array with a non-iterable or too-large an iterable '{user_value}', CType '{type_match}'"
                    )

                out_blob = bytearray()
                for entry_value in user_value:
                    try:
                        out_blob.extend(
                            self._flatten_and_write(ctypes, entry_value, entry_type)
                        )
                    except Exception as e:
                        raise Exception(
                            f"Exception occurred while filling field of array CType '{type_match}'`"
                        ) from e

                type_size = type_match.calc_byte_size()

                # Pad the remaining array entries
                assert len(out_blob) <= type_size
                out_blob.extend(bytes(type_size - len(out_blob)))

                # Strings must be null-terminated
                if entry_type.name == "char" and out_blob[-1] != 0:
                    raise ValueError(
                        f"Arrays of chars must be zero terminated, string '{user_value!r}', CType '{type_match}'"
                    )

                return bytes(out_blob)
            case "structure_type":
                if not type_match.byte_size:
                    raise ValueError(
                        f"Cannot fill a struct with no byte size {type_match}"
                    )

                member_types = list(
                    type_match.ctypes[child_id] for child_id in type_match.children
                )
                member_names = set(m.name for m in member_types)

                if None in member_names:
                    raise ValueError(
                        f"Anonymous struct member (e.g. unions) are not supported by ConfigStruct serializer ({type_match})"
                    )

                # Every member must have a field value, and vice versa
                if set(user_value.fields) != member_names:
                    raise ValueError(
                        f"User provided keys '{set(user_value.fields)}' do not match structure type member names '{member_names}', CType '{type_match}'"
                    )

                out_blob = bytearray()
                for member in sorted(
                    member_types,
                    key=lambda m: (
                        m.data_member_location
                        if m.data_member_location is not None
                        else 0
                    ),
                ):
                    if member.data_member_location is None:
                        raise ValueError(
                            f"Member type '{member}' does not support struct members without byte offset locations (bit offsets are not supported)"
                        )

                    # Pad up to this member
                    assert len(out_blob) <= member.data_member_location
                    out_blob.extend(bytes(member.data_member_location - len(out_blob)))

                    member_value = user_value.fields[member.name]
                    member_type = member.find_base_type(False)
                    try:
                        out_blob.extend(
                            self._flatten_and_write(
                                ctypes,
                                member_value,
                                member_type,
                            )
                        )
                    except Exception as e:
                        raise Exception(
                            f"Exception occurred while filling member {member.name}, (type = {member_type}) with value {member_value} of structure CType '{type_match}'`"
                        ) from e

                assert len(out_blob) <= type_match.byte_size
                out_blob.extend(bytes(type_match.byte_size - len(out_blob)))
                return bytes(out_blob)
            case _:
                raise ValueError(f"Trying to flatten unexpected CType '{type_match}'")

    def resolve_and_create_all(self, dump: bool = False):
        """
        Try generate data files for all currently known config structs. Output
        will be placed in `self.build_dir`.
        """
        for config_struct in self.config_structs:
            if config_struct.target_file is None:
                raise RuntimeError(
                    f"Top level config struct {config_struct} has no target file!"
                )
            if config_struct.type_name is None:
                raise RuntimeError(
                    f"Top level config struct {config_struct} has no type name!"
                )

            match = find_ctype_by_name(
                self.files[config_struct.target_file], config_struct.type_name
            )
            if not match:
                raise ValueError(
                    f"Could not find CType match with name {config_struct.type_name}"
                )
            match = match.find_base_type(False)

            try:
                blob = self._flatten_and_write(
                    self.files[config_struct.target_file], config_struct, match
                )
            except Exception as e:
                raise Exception(
                    f"Exception occurred while flattening config struct '{config_struct}' into structure CType '{match}'`"
                ) from e

            blob_name = f"{str(config_struct.target_file).removesuffix('.elf')}_{config_struct.section_name}.data"
            blob_path = os.path.join(self.build_dir, blob_name)
            with open(blob_path, "wb") as f:
                f.write(blob)

            if dump:
                json_path = f"{blob_path.removesuffix('.data')}.json"
                with open(json_path, "w") as f:
                    json.dump(
                        {
                            "type_name": config_struct.type_name,
                            "section_name": str(config_struct.section_name),
                            "target_file": str(config_struct.target_file),
                            "empty": config_struct.empty,
                            "fields": {
                                name: _value_to_jsonable(value)
                                for name, value in config_struct.fields.items()
                            },
                        },
                        f,
                        indent=2,
                    )
                    f.write("\n")


def _value_to_jsonable(value: Any) -> Any:
    """
    Create JSON-friendly values for configstruct fields.
    ConfigStruct            -> {"empty": <bool>, "fields": {...}}
    bytes/bytearray/int     -> hex string
    list/tuple              -> list
    str/float/bool/None     -> unchanged
    """
    if isinstance(value, ConfigStruct):
        return {
            "empty": value.empty,
            "fields": {name: _value_to_jsonable(v) for name, v in value.fields.items()},
        }
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, int):
        return hex(value)
    if isinstance(value, (list, tuple)):
        return [_value_to_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, float, bool)):
        return value
    raise TypeError(
        f"Value '{value!r}' of type '{type(value).__name__}' is not JSON-serialisable"
    )
