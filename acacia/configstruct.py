# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
from __future__ import annotations
import pathlib, os, subprocess
from lark import Lark, Tree, Token
from dataclasses import dataclass
from ctypes import (
    c_uint8,
    c_uint16,
    c_uint32,
    c_uint64,
    c_int8,
    c_int16,
    c_int32,
    c_int64,
    c_float,
    c_double,
    c_longdouble,
    c_ubyte,
    c_byte,
    c_bool,
)
from collections.abc import Sized, Iterable
from typing import List, Tuple, Dict, Optional, Any, Union

dwarf_dump_grammar = r"""
    start : entry+

    ?entry :          compile_unit
                    | unknown_tag
                    | null "\n"
                    | single
                    | group

    id : "0x" HEX_ID

    null : id ":" "NULL\n"

    compile_unit : [null] id ": Compile Unit:" _IGNORE_UNTIL_NEWLINE "\n\n"

    unknown_tag : id ":" "DW_TAG_" _IGNORE_UNTIL_NEWLINE ["\n" _IGNORE_UNTIL_NEWLINE]+ "\n\n"

    single :          id ":" "DW_TAG_base_type\n" attribute* "\n" -> base_tag
                    | id ":" "DW_TAG_typedef\n" attribute* "\n" -> typedef_tag
                    | id ":" "DW_TAG_pointer_type\n" attribute* "\n" -> pointer_tag

    group_tag :       id ":" "DW_TAG_array_type\n" attribute* "\n" -> array_tag
                    | id ":" "DW_TAG_enumeration_type\n" attribute* "\n" -> enumeration_tag
                    | id ":" "DW_TAG_union_type\n" attribute* "\n" -> union_tag
                    | id ":" "DW_TAG_structure_type\n" attribute* "\n" -> structure_tag

    member_tag :      id ":" "DW_TAG_member\n" attribute* "\n" -> member_tag
                    | id ":" "DW_TAG_subrange_type\n" attribute* "\n" -> subrange_tag
                    | id ":" "DW_TAG_enumerator\n" attribute* "\n" -> enumerator_tag

    group : group_tag (member_tag | group)+ null "\n"

    attribute : "DW_AT_" at_name "(" at_value ")\n"

    !at_name :        "name"
                    | "encoding"
                    | "byte_size"
                    | "type"
                    | "decl_file"
                    | "decl_line"
                    | "decl_column"
                    | "sibling"
                    | "data_member_location"
                    | "upper_bound"
                    | "count"
                    | "alignment"
                    | "const_value"

    at_value :        ESCAPED_STRING -> escaped_string
                    | NUMBER -> number
                    | BARE_STRING -> string
                    | at_value at_value -> pair

    # Terminals
    HEX_ID : ("0".."9"|"a".."f")~8
    HEX_NUMBER : "0x" HEXDIGIT+
    NUMBER : (SIGNED_INT | HEX_NUMBER)
    BARE_STRING : /[A-Za-z_0-9+\-]+/
    _IGNORE_UNTIL_NEWLINE : /.+/

    %import common.ESCAPED_STRING
    %import common.HEXDIGIT
    %import common.SIGNED_INT

    %ignore " "
    %ignore "\t"
"""


@dataclass
class Attributes:
    """
    Class encapsulating tag attributes in the parsed output of llvm-dwarfdump on
    a file. Examples:

        attribute
            at_name	name
            escaped_string	"i2c_cmd_t"

         attribute
           at_name	type
           pair
             number	0x000001a5
             escaped_string	"i2c_cmd"

    Sanity checks values for each attribute.
    """

    valid_attributes = (
        "name",
        "decl_file",
        "encoding",
        "byte_size",
        "const_value",
        "decl_line",
        "decl_column",
        "data_member_location",
        "upper_bound",
        "count",
        "alignment",
        "type",
        "sibling",
    )

    @staticmethod
    def escaped_string(value_tree: Tree) -> str:
        """
        Returns the un-escaped string value from lark trees of the form:
            escaped_string  "DW_ATE_unsigned_32"
        """
        if value_tree.data != "escaped_string":
            raise ValueError(f"Expected escaped_string, found '{value_tree.pretty()}'")
        assert isinstance(value_tree.children[0], Token)
        return value_tree.children[0].value[1:-1]

    @staticmethod
    def string(value_tree: Tree) -> str:
        """
        Returns the string value from lark trees of the form:
            string	DW_ATE_unsigned
        """
        if value_tree.data != "string":
            raise ValueError(f"Expected string, found '{value_tree.pretty()}'")
        assert isinstance(value_tree.children[0], Token)
        return value_tree.children[0].value

    @staticmethod
    def number(value_tree: Tree) -> int:
        """
        Returns the numeric value from lark trees of the form:
            number	0x04
        """
        if value_tree.data != "number":
            raise ValueError(f"Expected number, found '{value_tree.pretty()}'")
        assert isinstance(value_tree.children[0], Token)
        value = value_tree.children[0].value
        if value.startswith('0x'):
            return int(value, base=16)
        return int(value)

    @staticmethod
    def id_number(value_tree: Tree) -> int:
        """
        Returns the numeric value from lark trees of the form:
            number	0x0000005b
        """
        if value_tree.data != "number":
            raise ValueError(f"Expected number, found '{value_tree.pretty()}'")
        assert isinstance(value_tree.children[0], Token)
        value = value_tree.children[0].value
        if not value.startswith('0x') or len(value) != 10:
            raise ValueError(f"Expected type ID, found '{value}'")
        return int(value, base=16)

    @staticmethod
    def pair(value_tree: Tree) -> Tuple[int, str]:
        """
        Returns a tuple of the numeric value and string from lark trees of the form:
            pair
            number	0x0000005b
            escaped_string	"int"
        """
        if value_tree.data != "pair" or len(value_tree.children) != 2:
            raise ValueError(f"Expected pair, found '{value_tree.pretty()}'")
        number = Attributes.id_number(value_tree.children[0])
        escaped_string = Attributes.escaped_string(value_tree.children[1])
        return number, escaped_string

    def extract_attribute(self, tree: Tree):
        """
        Given an attribute tree of the form:
            attribute
                at_name	name
                escaped_string	"i2c_cmd_t"
        extract the value of the attribute.
        """
        if tree.data != "attribute":
            raise ValueError(f"Expected attribute tree, found '{tree.pretty()}'")

        assert isinstance(tree.children[0].children[0], Token)
        at_name = tree.children[0].children[0].value
        if at_name not in self.valid_attributes:
            raise ValueError(
                f"Found invalid attribute name '{at_name}' in attribute '{tree.pretty()}'"
            )

        setattr(self, at_name, tree.children[1])

    def __getattr__(self, name: str):
        if name in self.__dict__:
            return self.__dict__[name]
        elif name in self.valid_attributes:
            return None
        else:
            raise AttributeError(f"Attributes class has no attribute '{name}'")

    def __setattr__(self, name: str, value: Union[tuple, Tree]):
        if name == "valid_attributes":
            object.__setattr__(self, name, value)

        assert isinstance(value, Tree)

        if name in self.__dict__:
            raise AttributeError(
                f"Attempting to reset initialised attribute '{name}' from '{self.__dict__[name]}' to '{value.pretty()}'"
            )

        at_value: Union[str, int, Tuple[int, str]]
        match name:
            case at_name if at_name in ("name", "decl_file"):
                at_value = self.escaped_string(value)
            case "encoding":
                encoding = self.string(value)
                if not encoding.startswith("DW_ATE_"):
                    raise ValueError(
                        f"Found an encoding attribute '{encoding}' without the 'DW_ATE_' prefix"
                    )
                at_value = encoding[7:]
            case "byte_size":
                at_value = self.number(value)
                if at_value <= 0:
                    raise ValueError(f"Found a non positive byte size '{at_value}'")
            case "const_value":
                at_value = self.number(value)
            case "type":
                at_value = self.pair(value)
            case "sibling":
                at_value = self.id_number(value)
            case at_name if at_name in (
                "decl_line",
                "decl_column",
                "data_member_location",
                "upper_bound",
                "count",
                "alignment",
            ):
                at_value = self.number(value)
                if at_value < 0:
                    raise ValueError(f"Found a negative {name} '{at_value}'")
            case _:
                raise AttributeError(f"Attributes class has no attribute '{name}'")

        object.__setattr__(self, name, at_value)

    def __repr__(self):
        return "Attributes:\n    " + "\n    ".join([f"{at_name}: {getattr(self, at_name)}" for at_name in self.valid_attributes]) + "\n"


class CType:
    """
    Class encapsulating a tag entry or C type found in the parsed output of
    llvm-dwarfdump on a file. Examples:

        unknown_tag
            id	0000000c

    or

      base_tag
        id	0000002b
        attribute
          at_name	name
          escaped_string	"DW_ATE_unsigned_32"
        attribute
          at_name	encoding
          string	DW_ATE_unsigned
        attribute
          at_name	byte_size
          number	0x04

    or

        group
            structure_tag
              id	000000f9
              attribute
                ...
            member_tag
              id	000000fe
              attribute
                ...
            member_tag
              id	00000107
              attribute
                ...
            null
              id	00000110
    """

    special_tags = (
        "unknown_tag",
        "null",
        "compile_unit",
    )

    single_tags = (
        "base_tag",
        "typedef_tag",
        "pointer_tag",
    )

    member_tags = (
        "subrange_tag",
        "enumerator_tag",
        "member_tag",
    )

    group_tags = {
        "array_tag": ("subrange_tag"),
        "enumeration_tag": ("enumerator_tag"),
        "union_tag": ("member_tag", "group"),
        "structure_tag": ("member_tag", "group"),
    }

    required_attributes = {
        "base_tag": ["encoding", "byte_size"],
        "typedef_tag": ["name", "type"],
        "member_tag": ["data_member_location", "name", "type"],
        "array_tag": ["type"],
    }

    def __init__(self, entry_tree: Tree, type_collector: Dict[int, "CType"]):
        """
        Properties:
            tag_type: type of tag entry, must be a member of special_tags,
                single_tags, member_tags or group_tags
            id: numeric identifier
            attributes: tag entry attribute values
            members: IDs of member tags, non-empty only for group_tag types
        Args:
            entry_tree: The lark tree corresponding to the tag
            type_collector: A dictionary of ID to CType mappings of all the CTypes found in the parsed tree from
        """

        self.collector: Dict[int, CType] = type_collector
        self._id: Optional[int] = None
        self.attributes: Attributes = Attributes()
        self.members: List[int] = list()
        self.tag_type: str = entry_tree.data

        tag_children = entry_tree.children
        match self.tag_type:
            case "compile_unit":
                if len(tag_children) not in (1, 2):
                    raise ValueError(
                        f"Found a compile_unit tree with an invalid number of children '{len(tag_children)}' (expected 1 or 2), tree '{entry_tree.pretty()}'"
                    )
                for child in tag_children:
                    if child.data == "null":
                        CType(child, type_collector)
                    else:
                        self.id = self.extract_id(child)
            case "group":
                if len(tag_children) < 2:
                    raise ValueError(
                        f"Found a group tree with an invalid number of children '{len(tag_children)}' (expected > 2), tree '{entry_tree.pretty()}'"
                    )
                leader = CType(tag_children[0], type_collector)
                for member in tag_children[1:-1]:
                    member = CType(member, type_collector)
                    if member.tag_type not in self.group_tags[leader.tag_type]:
                        raise ValueError(
                            f"Found an unexpected member tag '{member.tag_type}' in group tag '{leader.tag_type}' (expected '{self.group_tags[leader.tag_type]}'), tree '{entry_tree.pretty()}'"
                        )
                    if member.id:
                        leader.members.append(member.id)
                if CType(tag_children[-1], type_collector).tag_type != "null":
                    raise ValueError(
                        f"Found a group tree with non-null final child, tree '{entry_tree.pretty()}'"
                    )
            case tag if (
                tag in self.special_tags
                or self.single_tags
                or self.member_tags
                or self.group_tags
            ):
                if len(tag_children) == 0:
                    raise ValueError(
                        f"Found a '{self.tag_type}' tree with no ID, tree '{entry_tree.pretty()}'"
                    )
                self.id = self.extract_id(tag_children[0])
                for child in tag_children[1:]:
                    self.attributes.extract_attribute(child)
            case _:
                raise ValueError(
                    f"Found an unknown tag type: '{self.tag_type}', tree '{entry_tree.pretty()}'"
                )

        if self.tag_type in self.required_attributes:
            for attribute in self.required_attributes[self.tag_type]:
                if self.attributes.__getattr__(attribute) is None:
                    raise AttributeError(
                        f"CType of type '{self.tag_type}' is missing required attribute '{attribute}', CType '{self}'"
                    )

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, new_id: int):
        if self._id is not None:
            raise AttributeError(
                f"Attempted to reset initialised ID from '{self._id}' to '{new_id}', CType '{self}"
            )
        elif new_id in self.collector:
            raise ValueError(
                f"Attempted to reuse ID '{new_id}' from existing CType '{self.collector[new_id]}' for new CType '{self}'"
            )
        self._id = new_id
        self.collector[new_id] = self

    def base_type(self) -> CType:
        """
        Find the underlying base type of a CType.

        Returns self for all CTypes with types not in "typedef_tag",
        "member_tag" or "array_tag".
        """
        if self.tag_type not in ("typedef_tag", "member_tag", "array_tag"):
            return self

        if self.attributes.alignment is not None:
            raise ValueError(
                f"Requesting base type of CType '{self}' with non-zero alignment '{self,self.attributes.alignment}' (not supported)"
            )

        base_type = self.collector[self.attributes.type[0]]
        while base_type.tag_type == "typedef_tag":
            base_type = self.collector[base_type.attributes.type[0]]

        if base_type.tag_type in (self.special_tags or self.member_tags):
            raise ValueError(
                f"CType '{self}' resolved to base type '{base_type}' of invalid tag type '{base_type.tag_type}'"
            )
        return base_type

    def array_count(self) -> int:
        """
        Find the number of entries in an "array_tag" CType. Returns 0 if the
        subrange type does not have a count attribute.
        """
        if self.tag_type != "array_tag":
            raise TypeError(
                f"Provided CType tag '{self.tag_type}' is not an 'array_tag'"
            )
        subrange_type = self.collector[self.members[0]]
        if subrange_type.attributes.count is not None:
            return subrange_type.attributes.count
        return 0

    @staticmethod
    def extract_id(id_tree: Tree):
        """
        Returns the numeric value from lark trees of the form:
            id 0000423e
        """
        if id_tree.data != "id":
            raise ValueError(f"Expected ID tree, found '{id_tree}'")
        assert isinstance(id_tree.children[0], Token)
        id_string = id_tree.children[0].value
        return int(id_string, base=16)

    @staticmethod
    def sanity_check_type_ids(all_types: Dict[int, CType]):
        """
        Given a complete dictionary of type IDs to CTypes, ensure all type ID
        references are contained in the dictionary.
        """
        for new_type in all_types.values():
            if new_type.tag_type in ("typedef_tag", "member_tag", "array_tag"):
                if new_type.attributes.type[0] not in all_types:
                    raise ValueError(
                        f"Base type ID {new_type.attributes.type[0]} is not a valid type, CType '{new_type}'"
                    )
            if new_type.tag_type == "array_tag":
                if len(new_type.members) != 1:
                    raise ValueError(
                        f"Array type has the wrong number of members '{len(new_type.members)}', expected 1 (subrange type), CType '{new_type}'"
                    )

    @staticmethod
    def find_type_by_name(all_types: Dict[int, CType], type_name: str) -> CType:
        """
        Given a type name, find the underlying base type.
        """
        type_match = []
        for c_type in all_types.values():
            if c_type.attributes.name == type_name:
                type_match.append(c_type)

        if len(type_match) == 0:
            raise ValueError(f"Could not find a type with name '{type_name}'")
        elif len(type_match) > 1:
            raise ValueError(
                f"Found multiple types with name '{type_name}': {type_match}"
            )
        return type_match[0].base_type()

    def __repr__(self):
        ret_string = f"CType:\n    ID: {self.id}\n    type: {self.tag_type}\n    members: {self.members}\n"
        ret_string += self.attributes.__repr__()
        return ret_string


class ConfigStruct:
    """
    Python representation of a C configuration struct. This class provides a
    template for creating a configuration struct which will be serialised into a
    matching C struct found in a component's ELF file.
    """

    def __init__(
        self,
        fields: Dict[str, Any],
        type_name: Optional[str] = None,
        section_name: Optional[pathlib.Path] = None,
        target_file: Optional[pathlib.Path] = None,
    ):
        """
        Args:
            fields: dictionary of field names -> values. Can be:
                a. Another ConfigStruct
                b. Any int-like value
                c. Any string or bytes
                d. A list of values
            type_name: type of struct in C
            section_name: name of section to patch config struct into
            target_file: ELF file this will be patched into
        """
        self.fields = fields
        self.type_name = type_name
        self.section_name = section_name
        self.target_file = target_file

    def __repr__(self):
        return f"<ConfigStruct {self.type_name} {self.fields}>"


BaseTypesMap: Dict[str, Dict[int, Any]] = {
    "unsigned": {
        1: c_uint8,
        2: c_uint16,
        4: c_uint32,
        8: c_uint64,
    },
    "signed": {
        1: c_int8,
        2: c_int16,
        4: c_int32,
        8: c_int64,
    },
    "float": {
        4: c_float,
        8: c_double,
        16: c_longdouble,
    },
    "boolean": {
        1: c_bool,
    },
    "unsigned_char": {
        1: c_ubyte,
    },
    "signed_char": {
        1: c_byte,
    },
}


class ConfigStructResolver:
    """
    This class records all configuration structs of a system. As structs are
    added to this class, their target files are dwarf dumped and parsed, and all
    CTypes they contain are collected into a dictionary.

    Once all structs of the system are added, they are serialised one-by-one
    based on the memory layout of their types derived from the DWARF symbols in
    the ELF file. Each serialised struct is then written to a file in the build
    directory.
    """

    def __init__(
        self,
        build_dir: pathlib.Path,
        endian="little",
        dwarfdump_name: str = "llvm-dwarfdump",
    ):
        """
        Args:
            build_dir: name of the build directory, used for emitting serialised
                structs
            endian: endianness of encoding
            dwarfdump_name: name of dwarf dump command
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
        if s.section_name is None:
            raise ValueError("Cannot emit a config struct without a section name!")
        if s.target_file is None:
            raise ValueError("Cannot patch in a config struct without a target file!")
        if s.type_name is None:
            raise ValueError("Cannot patch in a config struct without a type name!")

        if s.target_file not in self.files:
            self.files[s.target_file] = self.resolve_target_file(s.target_file)

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
        if output.returncode != 0:
            raise RuntimeError(f"Couldn't dump {target_file} -> {output.stderr}")

        # Remove lines before first tag entry and add extra newline
        raw_lines = output.stdout.splitlines()
        for i in range(len(raw_lines)):
            if raw_lines[i][:11].startswith("0x00000000:"):
                break

        if i == len(raw_lines):
            raise RuntimeError(
                "Could not find tag entry with ID 0 in DWARF dump output"
            )

        raw_output = "\n".join(raw_lines[i:]) + "\n\n"

        try:
            output_tree = Lark(
                dwarf_dump_grammar,
                parser="lalr",
                propagate_positions=False,
                maybe_placeholders=False,
            ).parse(raw_output)
        except:
            raise RuntimeError("Could not parse DWARF dump output!")

        type_collector: Dict[int, CType] = dict()
        for dwarf_entry in output_tree.children:
            assert isinstance(dwarf_entry, Tree)
            CType(dwarf_entry, type_collector)

        CType.sanity_check_type_ids(type_collector)
        return type_collector

    def _flatten_and_write(self, user_value: Any, c_type: CType) -> bytearray:
        """
        Serialise the provided user value as an instance of the provided CType.
        """
        out_blob = bytearray()
        type_size = c_type.attributes.byte_size

        match c_type.tag_type:
            case "pointer_tag":
                type_size = 8
                try:
                    # We assume pointers are 8 byte unsigned
                    py_ctype = c_uint64(user_value)
                except Exception as e:
                    raise ValueError(
                        f"Could not create C pointer type from value '{user_value}'"
                    ) from e
                if user_value != py_ctype.value:
                    raise ValueError(
                        f"Could not represent '{user_value}' as C base type '{c_uint64.__name__}', got '{py_ctype.value}'"
                    )

                py_bytes = bytes(py_ctype)
                out_blob.extend(py_bytes)
                assert len(out_blob) == type_size
            case "base_tag":
                if (
                    c_type.attributes.encoding not in BaseTypesMap
                    or type_size not in BaseTypesMap[c_type.attributes.encoding]
                ):
                    raise ValueError(
                        f"Found base tag type with unexpected encoding {c_type.attributes.encoding} and byte size {type_size}"
                    )
                ctype_cls = BaseTypesMap[c_type.attributes.encoding][type_size]

                if isinstance(user_value, str) or isinstance(user_value, bytes):
                    if c_type.attributes.encoding in ("unsigned, signed, float, boolean"):
                        raise ValueError(
                            f"User provided string or bytes value '{user_value}' which cannot be used for C Base type '{ctype_cls.__name__}', CType '{c_type}'"
                        )

                    if len(user_value) != 1:
                        raise ValueError(
                            f"User provided value '{user_value}' which cannot be used for C Base type '{ctype_cls.__name__}', CType '{c_type}'"
                        )

                    if isinstance(user_value, str):
                        py_bytes = user_value.encode()
                    else:
                        py_bytes = user_value

                else:
                    try:
                        py_ctype = ctype_cls(user_value)
                    except Exception as e:
                        raise ValueError(
                            f"Could not create C base type '{ctype_cls.__name__}' from value '{user_value}'"
                        ) from e

                    if user_value != py_ctype.value:
                        raise ValueError(
                            f"Could not represent '{user_value}' as C base type '{ctype_cls.__name__}', got '{py_ctype.value}'"
                        )

                    py_bytes = bytes(py_ctype)

                out_blob.extend(py_bytes)
                assert len(out_blob) == type_size
            case "array_tag":
                entry_type = c_type.base_type()
                if not c_type.array_count() or not entry_type.attributes.byte_size:
                    raise ValueError(
                        f"Can't fill an array with size = count '{c_type.array_count()}' * entry_size '{entry_type.attributes.byte_size}' == 0, CType '{c_type}'"
                    )

                if (
                    not (isinstance(user_value, List)
                         or isinstance(user_value, Tuple)
                         or isinstance(user_value, str)
                         or isinstance(user_value, bytes)
                         or isinstance(user_value, bytearray))
                    or len(user_value) > c_type.array_count()
                ):
                    raise ValueError(
                        f"Can't fill an array with a non-iterable or too-large an iterable '{user_value}', CType '{c_type}'"
                    )

                for entry_value in user_value:
                    out_blob.extend(self._flatten_and_write(entry_value, entry_type))

                type_size = c_type.array_count() * entry_type.attributes.byte_size

                # Strings must be null-terminated
                if entry_type.attributes.name == "char":
                    if len(out_blob) == type_size and out_blob[-1] != 0:
                        raise ValueError(
                            f"Arrays of chars must be zero terminated, string '{user_value}', CType '{c_type}'"
                        )

                # Pad the remaining array entries
                assert len(out_blob) <= type_size
                out_blob.extend(bytearray(type_size - len(out_blob)))
            case "structure_tag":
                member_types = list(
                    c_type.collector[member_id] for member_id in c_type.members
                )

                # Every member must have a field value, and vice versa
                if set(user_value.fields.keys()) != set(
                    member.attributes.name for member in member_types
                ):
                    raise ValueError(
                        f"User provided keys '{set(user_value.fields.keys())}' do not match structure type member names '{set(member.attributes.name for member in member_types)}', CType '{c_type}'"
                    )

                for member in sorted(
                    member_types, key=lambda m: m.attributes.data_member_location
                ):
                    start_byte = member.attributes.data_member_location

                    # Pad up to this member
                    assert len(out_blob) <= start_byte
                    out_blob.extend(bytearray(start_byte - len(out_blob)))

                    member_value = user_value.fields[member.attributes.name]
                    out_blob.extend(
                        self._flatten_and_write(member_value, member.base_type())
                    )

                assert len(out_blob) <= type_size
                out_blob.extend(bytearray(type_size - len(out_blob)))
            case _:
                raise ValueError(f"Trying to flatten unexpected CType '{c_type}'")

        return out_blob

    def resolve_and_create_all(self):
        """
        Try generate data files for all currently known config structs. Output
        will be placed in `self.build_dir`.
        """
        for config_struct in self.config_structs:
            c_type = CType.find_type_by_name(
                self.files[config_struct.target_file], config_struct.type_name
            )
            blob = self._flatten_and_write(config_struct, c_type)
            blob_name = f"{config_struct.target_file.split('.elf')[0]}_{config_struct.section_name}.data"
            blob_path = os.path.join(self.build_dir, blob_name)
            with open(blob_path, "wb") as f:
                f.write(blob)
