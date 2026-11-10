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

# TODO:
# - declarations
# - Handle multi-dimensional arrays and variable length like net queue
# - empty structs?
# - test jsonify
# - docs
# - mypy

class c_type:
    def __init__(self, tag_type: str):
        self.tag_type = tag_type
        self.children = dict()
        self.attributes = dict()

    # Raw line: DW_AT_name	("usize"), captured value: "usize"
    @property
    def name(self) -> Optional[str]:
        if "name" in self.attributes:
            return self.attributes["name"][1:-1]
        return None

    # Raw line: DW_AT_type	(0x00000068 "usize"), captured value: 0x00000068 "usize"
    @property
    def base_type_id(self) -> Optional[int]:
        if "type" in self.attributes:
            return int(self.attributes["type"][2:10], base=16)
        return None

    # Raw line: DW_AT_count	(0x01), captured value: 0x01
    # OR Raw line: DW_AT_upper_bound	(0x14), captured value: 0x14 -- this is the last valid index
    @property
    def count(self) -> Optional[int]:
        if "count" in self.attributes:
            return int(self.attributes["count"][2:], base=16)
        if "upper_bound" in self.attributes:
            return int(self.attributes["count"][2:], base=16) + 1
        return None

    # Raw line: DW_AT_byte_size	(0x08), captured value: 0x08
    @property
    def byte_size(self) -> Optional[int]:
        if "byte_size" in self.attributes:
            return int(self.attributes["byte_size"][2:], base=16)
        return None

    # Raw line: DW_AT_data_member_location	(0x00), captured value: 0x00
    @property
    def data_member_location(self) -> Optional[int]:
        if "data_member_location" in self.attributes:
            return int(self.attributes["data_member_location"][2:], base=16)
        return None

    # Raw line: DW_AT_encoding	(DW_ATE_unsigned), captured value: DW_ATE_unsigned
    @property
    def encoding(self) -> Optional[str]:
        if "encoding" in self.attributes:
            return self.attributes["encoding"][7:]
        return None

    def __eq__(self, other):
        # TODO: Write
        return True

    def __repr__(self):
        return f"\n{self.tag_type}: {self.name}\nAttributes:\n{self.attributes}\nChildren:\n{self.children}\n"


def find_c_type_by_id(c_types: Dict[int, c_type], target_id: int) -> Optional[c_type]:
    for entry_id in c_types:
        if entry_id == target_id:
            return c_types[entry_id]

        child_match = find_c_type_by_id(c_types[entry_id].children, target_id)
        if child_match:
            return child_match

    return None


def find_base_type(
    c_types: Dict[int, c_type], raw_type: c_type, resolve_array_type: bool
) -> c_type:
    if not raw_type.base_type_id or (
        not resolve_array_type and raw_type.tag_type == "array_type"
    ):
        return raw_type

    base_type = find_c_type_by_id(c_types, raw_type.base_type_id)
    if not base_type:
        raise ValueError(
            f"Could not find base type ({raw_type.base_type_id}) of c_type {raw_type}"
        )

    return find_base_type(c_types, base_type, resolve_array_type)


def find_c_type_by_name(c_types: Dict[int, c_type], name: str) -> Optional[c_type]:
    matches = list()
    for entry in c_types.values():
        child_match = find_c_type_by_name(entry.children, name)
        if child_match:
            matches.append(child_match)

        if entry.name == name:
            matches.append(entry)

    match = None
    for next_match in matches:
        if match == None:
            match = next_match
            continue
        elif match != next_match:
            raise ValueError(
                f"Found two distinct c_types with the same name ({name}), {match} {next_match}"
            )

    return match


def find_array_count(array_type: c_type) -> List[Optional[int]]:
    subrange_counts = list()
    for subrange_type in array_type.children.values():
        if subrange_type.tag_type != "subrange_type":
            raise ValueError(
                f"ConfigStruct module does not support array types with non-subrange child types {array_type}"
            )

        subrange_counts.append(subrange_type.count)

    return subrange_counts


# Smallest whitespace between ID and tag name: 0x000000a9: DW_TAG_compile_unit
BASE_TAG_INDENT = 1

# Smallest whitespace before start of tag's attributes:              DW_AT_producer	("...")
BASE_ATTR_INDENT = 14

# Increase in whitespace per depth level (2nd depth level example): 0x000000c8:   DW_TAG_namespace
DEPTH_MULTIPLIER = 2


def eat_attributes(
    lines: List[str], start_idx: int, depth: int, c_type_attrs: Dict[str, str]
) -> int:
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

            c_type_attrs[attribute_match.group(2)] = attribute_value[1:-1]

        else:
            if not len(lines[start_idx]) == 0:
                raise ValueError(
                    f"Expected a tag attribute or empty line (line {start_idx}), found {lines[start_idx]}"
                )
            return start_idx + 1

    return start_idx


def eat_tag(
    lines: List[str], start_idx: int, depth: int, c_types: Dict[int, c_type]
) -> int:
    prev_id = 0
    while start_idx < len(lines):
        tag_match = re.match(r"^0x([0-9a-f]{8}):( +)DW_TAG_(.+)", lines[start_idx])
        if tag_match:
            tag_depth = (len(tag_match.group(2)) - BASE_TAG_INDENT) // DEPTH_MULTIPLIER
            if tag_depth == depth:
                prev_id = int(tag_match.group(1), base=16)
                c_types[prev_id] = c_type(tag_match.group(3))
                start_idx = eat_attributes(
                    lines, start_idx + 1, tag_depth, c_types[prev_id].attributes
                )
            elif tag_depth < depth:
                return start_idx
            elif tag_depth == depth + 1:
                start_idx = eat_tag(
                    lines, start_idx, depth + 1, c_types[prev_id].children
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
    c_types they contain are collected into a dictionary.

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
        self.files: Dict[pathlib.Path, Dict[int, c_type]] = dict()
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

    def resolve_target_file(self, target_file: pathlib.Path) -> Dict[int, c_type]:
        """
        Dwarf dump a target file, parse the output and collect all c_types into a dictionary.
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

        type_collector: Dict[int, c_type] = dict()
        eat_tag(output.stdout.splitlines(), 0, 0, type_collector)

        return type_collector

    def _flatten_and_write(
        self, c_types: Dict[int, c_type], user_value: Any, type_match: c_type
    ) -> bytes:
        """
        Returns the serialised bytes of the C type with value user_value. Used
        to create serialised configuration structs for Acacia components.

        This function is recursive. If the C type is an array or struct type,
        the function will call itself on each of the entries/members, until
        eventually a "base" type or "pointer" type is reached.

        The user value will then be serialised into bytes of the base C type
        using the ctypes module.

        The bytes of each struct member are then placed at the member's offset
        within the struct. Members are filled from offset 0 onwards. Zero-filled
        padding is added between members if the member's bytes do not reach the
        next offset.

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
                    # We assume pointers are 8 byte unsigned
                    return user_value.to_bytes(8, "little")
                except Exception as e:
                    raise ValueError(
                        f"Could not create C pointer type from value '{user_value}'"
                    ) from e

            case "base_type":
                try:
                    if isinstance(user_value, str) or isinstance(user_value, bytes):
                        if type_match.encoding not in ("unsigned_char", "signed_char"):
                            raise ValueError(
                                f"Strings and bytes are only supported for char encodings, not '{type_match.encoding}'"
                            )

                        assert len(user_value) == 1

                        if isinstance(user_value, str):
                            return user_value.encode()
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
                entry_type = find_base_type(c_types, type_match, True)
                array_count = find_array_count(type_match)

                # TODO: Multi dimension arrays and variable length arrays
                assert len(array_count) == 1 and array_count[0] != None
                array_count = array_count[0]

                if not entry_type.byte_size:
                    raise ValueError(
                        f"Can't fill an array with entries of size 0, c_type '{type_match}'"
                    )

                if (
                    not (
                        isinstance(user_value, list)
                        or isinstance(user_value, tuple)
                        or isinstance(user_value, str)
                        or isinstance(user_value, bytes)
                        or isinstance(user_value, bytearray)
                    )
                    or len(user_value) > array_count
                ):
                    raise ValueError(
                        f"Can't fill an array with a non-iterable or too-large an iterable '{user_value}', c_type '{type_match}'"
                    )

                out_blob = bytearray()
                for entry_value in user_value:
                    try:
                        out_blob.extend(
                            self._flatten_and_write(c_types, entry_value, entry_type)
                        )
                    except Exception as e:
                        raise Exception(
                            f"Exception occurred while filling field of array c_type '{type_match}'`"
                        ) from e

                type_size = array_count * entry_type.byte_size

                # Pad the remaining array entries
                assert len(out_blob) <= type_size
                out_blob.extend(bytes(type_size - len(out_blob)))

                # Strings must be null-terminated
                if entry_type.name == "char" and out_blob[-1] != 0:
                    raise ValueError(
                        f"Arrays of chars must be zero terminated, string '{user_value!r}', c_type '{type_match}'"
                    )

                return bytes(out_blob)
            case "structure_type":
                if not type_match.byte_size:
                    raise ValueError(
                        f"Cannot fill a struct with no byte size {type_match}"
                    )

                member_types = list(type_match.children.values())
                member_names = set(m.name for m in member_types)

                if None in member_names:
                    raise ValueError(
                        f"Anonymous struct member (e.g. unions) are not supported by ConfigStruct serializer ({type_match})"
                    )

                # Every member must have a field value, and vice versa
                if set(user_value.fields) != member_names:
                    raise ValueError(
                        f"User provided keys '{set(user_value.fields)}' do not match structure type member names '{member_names}', c_type '{type_match}'"
                    )

                out_blob = bytearray()
                for member in sorted(
                    member_types, key=lambda m: m.data_member_location
                ):
                    if member.data_member_location == None:
                        raise ValueError(
                            f"Member type '{member}' does not support struct members without byte offset locations (bit offsets are not supported)"
                        )

                    # Pad up to this member
                    assert len(out_blob) <= member.data_member_location
                    out_blob.extend(bytes(member.data_member_location - len(out_blob)))

                    member_value = user_value.fields[member.name]
                    member_type = find_base_type(c_types, member, False)
                    try:
                        out_blob.extend(
                            self._flatten_and_write(
                                c_types,
                                member_value,
                                member_type,
                            )
                        )
                    except Exception as e:
                        raise Exception(
                            f"Exception occurred while filling member of structure c_type '{type_match}'`"
                        ) from e

                assert len(out_blob) <= type_match.byte_size
                out_blob.extend(bytes(type_match.byte_size - len(out_blob)))
                return bytes(out_blob)
            case _:
                raise ValueError(f"Trying to flatten unexpected c_type '{type_match}'")

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

            match = find_c_type_by_name(
                self.files[config_struct.target_file], config_struct.type_name
            )
            if not match:
                raise ValueError(
                    f"Could not find c_type match with name {config_struct.type_name}"
                )
            match = find_base_type(self.files[config_struct.target_file], match, False)

            try:
                blob = self._flatten_and_write(
                    self.files[config_struct.target_file], config_struct, match
                )
            except Exception as e:
                raise Exception(
                    f"Exception occurred while flattening config struct '{config_struct}' into structure c_type '{match}'`"
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
