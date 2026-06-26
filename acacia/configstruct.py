# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from dataclasses import dataclass
from collections import defaultdict, deque
from ctypes import c_void_p, c_uint64, c_uint32, c_uint16, c_uint8, c_char, Array, Structure, sizeof
from ctypes import c_int64, c_int32, c_int16, c_int8
from typing import List, Dict, Optional, Tuple
import os, sys, subprocess
from .memory import Map

# approximately fine..?
c_uintptr = c_uint64
def uint_max(n):
    return (1 << n) - 1

# Microkit constants ... TODO: replace with something not hard coded
DEVICE_MAGIC_LEN = 5
DEVICE_MAX_REGIONS = 64
DEVICE_MAX_IRQS = 64

# TODO: support endianness changes using util ctypes wrapper
# WARNING: currently assumes host is little endian 64 bit!
# WARNING: currently assumes target is 64 bit!
# Sidenote: the Zig sdfgen made both of these assumptions too...

# NOTE: The code here that maps the ConfigStruct values into the binary blob
# can do with a bit more love.

class ConfigStruct:
    """
    Python representation of a config struct. This is
    effectively a template which is best-effort stored into
    the matching struct found in an ELF file.
    """
    typedef_name: str
    # Symbol name/target file is only needed for the top-level struct.
    section_name: Optional[str]
    target_file: Optional[str]
    # Dict of field names -> int values, other ConfigStruct ojects, or lists of either (arrays)
    fields: Dict[str, any]

    def __init__(self, typedef_name,  target_file=None, section_name=None, fields={}):
        """
        Args:
            typedef_name: type of struct in C
            target_file: ELF file this will be patched into.
            section_name: name of section OR symbol to patch config struct into
            fields: dictionary of field names -> values. Can be:
                a. Another ConfigStruct
                b. Any int-like value
                c. Any string
                d. A list of ConfigStructs of ints
            NOTE: we follow the existing sdfgen idiom here by
            assuming PDs are initialised with the name of a
            copied ELF file if they are duplicates. In future
            we could do this automatically...

            This can probably be done by subsystems by doing the ELF copy
            in-place. At any rate:
            **This method expects the copied ELF file!**
        """
        self.typedef_name = typedef_name
        self.target_file = target_file
        self.section_name = section_name
        # TODO: add datatype validation for fields. Not strictly needed as this should fail when
        # serialising anyway.
        self.fields = fields


    def __getitem__(self, key):
        return self.fields[key]

    def __contains__(self, key):
        return key in self.fields

    def __repr__(self):
        return f"<ConfigStruct {self.typedef_name}@{self.target_file} {self.fields}>"


@dataclass
class DwarfStructMember:
    field_name: str
    type_name: str
    entries: int    # How many array entries are there? 1 if not an array.
    offset: int


@dataclass
class DwarfStruct:
    type_name: str
    typedef_name: str
    size: int
    members: List[DwarfStructMember]

    def __eq__(self, o):
        if self.type_name != o.type_name:
            return False
        if self.typedef_name != o.typedef_name:
            return False
        if len(self.members) != len(o.members):
            return False
        for m in range(len(self.members)):
            if self.members[m] != o.members[m]:
                return False
        return True


# BUG: we currently have a hard time resolving some types from the C library
# I have added uintptr_t, size_t and void * here as a hack to get around
# this for now.
BaseTypesMap = {
    "char": c_char,
    "uint64_t": c_uint64,
    "uint32_t": c_uint32,
    "uint16_t": c_uint16,
    "uint8_t": c_uint8,
    "int64_t": c_int64,
    "int32_t": c_int32,
    "int16_t": c_int16,
    "int8_t": c_int8,
    "size_t": c_uint64,     # HACK: probs should handle this differently
    "uintptr_t": c_uint64,  # HACK: probs should handle this differently
    "void *": c_uint64,     # HACK: probs should handle this differently
    "_Bool": c_uint8,        # HACK: probs should handle this differently
}

class ConfigStructDwarfDumper:
    """
    Class encapsulating operating using llvm-dwarfdump as a subprocess call.
    """
    def __init__(self, build_dir: str, dwarfdump_name: str = "llvm-dwarfdump"):
        self.bin = dwarfdump_name
        self.build_dir = build_dir
        # Check that llvm-dwarfdump is available
        try:
            subprocess.run([self.bin, "--version"])
        except FileNotFoundError as e:
            print("Failed to find `llvm-dwarfdump`! Make sure it is installed and on your path...")
            raise RuntimeError(f"No LLVM DwarfDump! {e}")

        self.files = {}    # file_name -> List[List[str]]   each entry is a DW_Tag, grouped with child elements.
        self.file_structs = defaultdict(dict)  # file_name -> dict(struct_name -> index in `files`
        self.file_typedef_to_type = {}

    def _eat_dwarf(self, target_file):
        # Goblin delicacy
        ret = subprocess.run([self.bin, target_file], capture_output=True, text=True, check=True)
        if ret.returncode != 0:
            raise RuntimeError(f"Couldn't dump {target_file} -> {ret.stderr}")
        return ret

    def get_struct_by_typedef(self, target_file: str, typedef_name: str):
        true_type = self.get_typedef_base_type(target_file, typedef_name)
        return self.file_structs[target_file][true_type]

    def _parse_file(self, target_file: str):
        """
        Parse a dwarf file and record all DIEs that might be config struct relevant.
        """
        if target_file in self.files:
            raise RuntimeWarning("Trying to parse an already-parsed file!")

        elf = os.path.join(self.build_dir, target_file)
        raw = self._eat_dwarf(elf)

        # Create a list of lists, where each element is a single DW_TAG block broken up into lines.
        out = []
        curr = []
        for l in raw.stdout.splitlines():
            if len(l) <= 1:
                # New element
                if len(curr) != 0:
                    out.append(curr)
                    curr = []
            else:
                curr.append(l)
        self.files[target_file] = out
        self._dump_file(target_file)

    def _dump_file(self, target_file: str):
        def search_quotes(term, lines):
            try:
                return next(x.split('"')[1] for x in lines if term in x)
            except StopIteration:
                raise RuntimeError(f"Failed to find {term} in {lines}")

        # Now, scrape typedefs and associated struct types
        typedefs = {}  # type_name -> typedef_name
        struct_types = []
        for i, tag in enumerate(self.files[target_file]):
            if "DW_TAG_typedef" in tag[0]:
                # Bingo!
                # These fields sometimes are out of order, so we abuse `next` to search
                # for the fields we want.
                typedef_name = search_quotes("DW_AT_name", tag)
                if typedef_name in BaseTypesMap:
                    # We don't want to store type mappings for stdint.h types.
                    # The fixed width version is more informative!
                    continue
                type_name = search_quotes("DW_AT_type", tag)
                typedefs[type_name] = typedef_name

        # Do structs separately for neatness ... not ideal for performance. TODO: speedier?
        file = self.files[target_file]
        for i in range(len(file)):
            # Skip until struct found
            if "DW_TAG_structure_type" not in file[i][0]:
                continue

            # Now at a struct. The next several tags should be `DW_TAG_members`
            # representing the struct members.
            try:
                struct_name = search_quotes("DW_AT_name", file[i])
            except RuntimeError:
                # If name not found, this is an anonymous struct. Not one we care
                # about for config structs.
                continue

            # We don't care about this if there's no matching typedef
            if struct_name not in typedefs:
                continue

            # Get size
            size = int(next(x.split('(')[1].split(')')[0] for x in file[i] if "DW_AT_byte_size" in x), base=16)

            # If struct already discovered, we don't wanna store it
            already_discovered = struct_name in self.file_structs[target_file]
            # We can find the same struct twice when it is used
            # across multiple compile units as an include ... ugh!
            # For sanity, we check that this definition just *matches*.

            # Now clear to scrape members. Iterate ahead of outer loop `i`.
            members = []
            for u in range(i+1, len(file)):
                if "DW_TAG_member" not in file[u][0]:
                    # No more members!
                    break

                # Grab member deets
                member_name = search_quotes("DW_AT_name", file[u])
                member_type_raw = search_quotes("DW_AT_type", file[u])
                arr_size = 1
                member_type = member_type_raw

                # Separate out array size if existing
                if '[' in member_type_raw:
                    arr_size = member_type_raw.split('[')[1].split(']')[0]
                    member_type = member_type_raw.split('[')[0]

                offset = int(next(x.split('(')[1].split(')')[0] for x in file[u] if "DW_AT_data_member_location" in x), base=16)
                members.append(DwarfStructMember(member_name, member_type, arr_size, offset))

            if len(members) == 0:
                raise RuntimeWarning("Found a struct with no members!")

            # Check / store struct finally
            s = DwarfStruct(struct_name, typedefs[struct_name], size, members)
            if already_discovered:
                # Make sure discovered struct is exactly the same as what we expect.
                if s != self.file_structs[target_file][struct_name]:
                    # If this happens, we no longer have a source of truth!
                    raise RuntimeError(f"{s} is duplicated but instances are not identical!")
            else:
                self.file_structs[target_file][struct_name] = s

        self.file_typedef_to_type[target_file] = {typedefs[k]: k for k in typedefs.keys()}


    def discover_config_var(self, target_var, target_file) -> DwarfStruct:
        if target_file not in self.files:
            self._parse_file(target_file)

        search_quotes = lambda term, lines: next(x.split('"')[1] for x in lines if term in x)
        # Search file text to find variable definition
        # TODO: enable/add to logic here to pull out details for set_mr_prefill
        # / set_var_vaddr. Currently this is not needed.
        if False:
            for i, tag in enumerate(self.files[target_file]):
                if "DW_TAG_variable" in tag[0]:
                    name = search_quotes("DW_AT_name", tag)
                    if name != target_var:
                        continue
                    else:
                        # Found!
                        # TODO: do something with this
                        ...

    def find_struct_and_children(self, target_file, typedef_name) -> Tuple[DwarfStruct, List[DwarfStruct]]:
        """
        Given a typedef, return the DWARF representation of that struct, and a
        list of all child struct definitions (also in DWARF representation).
        """
        if target_file not in self.files:
            self._parse_file(target_file)

        # First: find struct
        top_struct = self.get_struct_by_typedef(target_file, typedef_name)

        # We now should have the DWARF struct for the top-level struct. The
        # next thing to do is to recursively find the DWARF struct for any
        # child structs (and any descendents of those child structs).
        # Fields in a `ConfigStruct` names paired with a Python value for
        # the field - i.e. another ConfigStruct, an `int`, a list of the latter
        # two, or a `str`. We want to find the field by name, divine the actual
        # type, and then try inject the Python value to that container.
        child_structs = []
        to_check = deque([x for x in top_struct.members])
        while len(to_check) != 0:
            curr = to_check.popleft()
            true_child_type = self.get_typedef_base_type(target_file, curr.type_name)
            if true_child_type in BaseTypesMap:
                continue    # Just an int type
            child_struct = self.get_struct_by_typedef(target_file, curr.type_name)
            child_structs.append(child_struct)
        return (top_struct, child_structs)

    def get_typedef_base_type(self, target_file, typedef_name):
        """
        Given a typedef name, find the underlying type recursively. I.e. this should
        end up with a structure OR a numeric type somewhere.
        """
        curr = typedef_name
        # We exit if we find something in the basetypesmap because there are
        # always terminal typedefs that map the fixed-width types to implementation-
        # defined C types like unsigned char. We don't actually want those for the
        # scope of building structs, so we just stop decoding!
        while curr in self.file_typedef_to_type[target_file] and curr not in BaseTypesMap:
            curr = self.file_typedef_to_type[target_file][curr]
        return curr

class ConfigStructResolver:
    """
    A representation of a configuration structure that will be patched
    into ELF files. This records:

        1. The target file to install data to,
        2. The specific struct to target,
        3. The values to install into the struct,
        4. The memory layout of the target struct, derived from the
           DWARF symbols in the ELF file.
    """
    def __init__(self, build_dir: str, endian='little',
                 dwarfdump_name: str = "llvm-dwarfdump"):
        """
        Args:
            target_file: name of elf file
            section_name: name of symbol to patch
            typedef_name: name of struct typedef in C
            pystruct: dict of field names, each containing either:
                      a. ctypes fixed-width containers with names matching struct fields
                      b. instances of child structs (identically formatted dicts).
            """

        self.files = defaultdict(list)
        self.dwarfdump = ConfigStructDwarfDumper(build_dir, dwarfdump_name=dwarfdump_name)
        self.build_dir = build_dir
        if endian != 'little':
            raise NotImplementedError("Big endian is not currently supported!")


    def add_struct(self, s: ConfigStruct):
        if s.section_name is None:
            raise ValueError("Cannot patch in a config struct without a symbol name to target!")
        if s.target_file is None:
            raise ValueError("Cannot patch in a config struct without a file target!")

        self.files[s.target_file].append(s)

    def add_structs(self, lst: List[ConfigStruct]):
        for s in lst:
            self.add_struct(s)

    def get_structs_by_file(self, target_file: str):
        return self.files[target_file]

    @staticmethod
    def _check_int_fits(value: int, ctype_cls, field_name: str):
        size_bits = sizeof(ctype_cls) * 8
        if issubclass(ctype_cls, (c_int8, c_int16, c_int32, c_int64)):
            lo = -(1 << (size_bits - 1))
            hi = (1 << (size_bits - 1)) - 1
            if not (lo <= value <= hi):
                raise ValueError(
                    f"Field '{field_name}': signed value {value} out of range for "
                    f"{ctype_cls.__name__} ({lo}..{hi})"
                )
        else:
            hi = (1 << size_bits) - 1
            if not (0 <= value <= hi):
                raise ValueError(
                    f"Field '{field_name}': unsigned value {value} out of range for "
                    f"{ctype_cls.__name__} (0..{hi})"
                )


    def _serialize_ctype(self, value, ctype_cls) -> bytes:
        """
        Serialize a single Python value into explicit little-endian raw bytes.
        Width is taken from ctypes via sizeof(), and signedness is derived from
        the ctypes class so we do not rely on host struct layout.
        """
        if ctype_cls is c_char:
            if isinstance(value, str):
                value = value.encode('utf-8')
            if isinstance(value, bytes):
                return value[:1] if value else b'\x00'
            return bytes([int(value) & 0xff])

        size = sizeof(ctype_cls)
        signed = issubclass(ctype_cls, (c_int8, c_int16, c_int32, c_int64))
        return int(value).to_bytes(size, byteorder='little', signed=signed)


    @staticmethod
    def _insert_bytes(blob: bytearray, offset: int, data: bytes):
        if offset < 0:
            raise ValueError(f"Negative offset {offset}")
        end = offset + len(data)
        if end > len(blob):
            raise ValueError(
                f"Write of {len(data)} bytes at offset {offset} exceeds blob size {len(blob)}"
            )
        blob[offset:end] = data


    def _flatten_and_write(self, blob: bytearray, dwarf_struct: DwarfStruct,
                           base_offset: int, py_fields: Dict[str, any], target_file: str):
        """
        Recursively unroll a DwarfStruct into *blob* at *base_offset*.
        Nested structs are inlined field-by-field; no ctypes.Structure layout
        is used, so host struct padding/alignment rules are never involved.
        """
        # (a) Every key supplied by the user must exist in the DWARF layout.
        member_names = {m.field_name for m in dwarf_struct.members}
        for field_name in py_fields.keys():
            if field_name not in member_names:
                raise ValueError(
                    f"ConfigStruct field '{field_name}' not found in DWARF struct "
                    f"'{dwarf_struct.typedef_name}' (members: {sorted(member_names)})"
                )

        for member in sorted(dwarf_struct.members, key=lambda m: m.offset):
            abs_offset = base_offset + member.offset
            field_name = member.field_name
            entries = int(member.entries)

            try:
                if field_name not in py_fields:
                    raise ValueError(f"Field {field_name} isn't in ConfigStruct but is in DWARF!")

                py_val = py_fields[field_name]
                resolved_type = self.dwarfdump.get_typedef_base_type(target_file, member.type_name)

                if resolved_type in BaseTypesMap:
                    ctype_cls = BaseTypesMap[resolved_type]
                    type_size = sizeof(ctype_cls)

                    if ctype_cls is c_char:
                        if isinstance(py_val, str):
                            data = py_val.encode('utf-8')
                        elif isinstance(py_val, bytes):
                            data = py_val
                        else:
                            raise TypeError(
                                f"Field '{field_name}': expected str or bytes for char type, "
                                f"got {type(py_val).__name__}"
                            )
                        total_extent = type_size * entries
                        if len(data) > total_extent:
                            raise ValueError(
                                f"Field '{field_name}': data length {len(data)} exceeds "
                                f"char array extent {total_extent}"
                            )
                        self._insert_bytes(blob, abs_offset, data)
                        if len(data) < total_extent:
                            blob[abs_offset + len(data):abs_offset + total_extent] = \
                                b'\x00' * (total_extent - len(data))

                    elif isinstance(py_val, list):
                        if len(py_val) > entries:
                            raise ValueError(
                                f"Field '{field_name}': list has {len(py_val)} elements, "
                                f"but DWARF expects at most {entries}"
                            )
                        for i, elem in enumerate(py_val):
                            elem_offset = abs_offset + i * type_size
                            if not isinstance(elem, int):
                                raise TypeError(
                                    f"Field '{field_name}': array element must be int, "
                                    f"got {type(elem).__name__}"
                                )
                            self._check_int_fits(elem, ctype_cls, field_name)
                            self._insert_bytes(blob, elem_offset, self._serialize_ctype(elem, ctype_cls))

                    elif isinstance(py_val, int):
                        if entries != 1:
                            raise ValueError(
                                f"Field '{field_name}': scalar integer provided for array "
                                f"field (expected {entries} entries)"
                            )
                        self._check_int_fits(py_val, ctype_cls, field_name)
                        self._insert_bytes(blob, abs_offset, self._serialize_ctype(py_val, ctype_cls))

                    else:
                        raise TypeError(
                            f"Field '{field_name}' of {member}: unsupported Python type {type(py_val).__name__} "
                            f"for primitive ctype {ctype_cls.__name__}"
                        )

                else:
                    # Struct type (or array of structs) – recurse after looking up layout.
                    try:
                        child_struct = self.dwarfdump.get_struct_by_typedef(target_file, member.type_name)
                    except (KeyError, RuntimeError) as e:
                        raise RuntimeError(
                            f"Field '{field_name}': unable to resolve struct type "
                            f"'{resolved_type}' (typedef '{member.type_name}')"
                        ) from e

                    if isinstance(py_val, ConfigStruct):
                        if entries != 1:
                            raise ValueError(
                                f"Field '{field_name}': scalar ConfigStruct provided for "
                                f"array field (expected {entries} entries)"
                            )
                        self._flatten_and_write(blob, child_struct, abs_offset,
                                                py_val.fields, target_file)
                    elif isinstance(py_val, int):
                        # Special case: allow assignment of 0 to structs that are unused
                        if py_val == 0:
                            pass
                        else:
                            raise TypeError("Cannot assign a non-zero int to a struct field!")

                    elif isinstance(py_val, list):
                        if len(py_val) > entries:
                            raise ValueError(
                                f"Field '{field_name}': list has {len(py_val)} elements, "
                                f"but DWARF expects at most {entries}"
                            )
                        stride = child_struct.size
                        for i, elem in enumerate(py_val):
                            elem_offset = abs_offset + i * stride
                            if not isinstance(elem, ConfigStruct):
                                raise TypeError(
                                    f"Field '{field_name}': expected ConfigStruct in list, "
                                    f"got {type(elem).__name__}"
                                )
                            self._flatten_and_write(blob, child_struct, elem_offset,
                                                    elem.fields, target_file)

                    else:
                        raise TypeError(
                            f"Field '{field_name}': unsupported Python type {type(py_val).__name__} "
                            f"for struct field"
                        )
            except Exception as e:
                e_type = type(e)
                raise e_type(f"While parsing {member} of {dwarf_struct} \n\n-> {e}") from e


    def resolve_file(self, target_file: str):
        """
        Resolve all structs for a given file, and emit binary blobs to patch in for
        all configstructs currently available. Blobs written directly to self.build_dir.
        """
        if target_file not in self.dwarfdump.files:
            self.dwarfdump._parse_file(target_file)

        for pystruct in self.files[target_file]:
            struct, _ = self.dwarfdump.find_struct_and_children(
                target_file, pystruct.typedef_name
            )

            blob = bytearray(struct.size)
            self._flatten_and_write(blob, struct, 0, pystruct.fields, target_file)

            blob_name = f"{pystruct.target_file.split('.elf')[0]}_{pystruct.section_name}.data"
            blob_path = os.path.join(self.build_dir, blob_name)
            with open(blob_path, 'wb') as f:
                f.write(blob)


    def resolve_all(self):
        """
        Try generate data files for all currently known config structs. Output
        will be placed in `self.build_dir`.
        """
        for f in self.files.keys():
            self.resolve_file(f)


    # These methods are stubs of an implementation using pyelftools...
    # def _index_dwarf(self, dwarf) -> Dict[str, Any]:
    #     """
    #     Index typedefs by DIE and return dict of names:dies
    #     """
    #     typedefs = {}
    #     for cu in dwarf.iter_CUs():
    #         for die in cu.iter_DIEs():
    #             if die.tag == 'DW_TAG_typedef' and 'DW_AT_name' in die.attributes:
    #                 name = die.attributes['DW_AT_name'].value
    #                 if isinstance(name, bytes):
    #                     name = name.decode('utf-8', errors='replace')
    #                 typedefs[name] = die
    #     return typedefs

    # def _index_symbols(self, elf) -> Dict[str, Any]:
    #     """
    #     Index symbols in ELF and return dict of names:symbols
    #     """
    #     symbols = {}
    #     for section in elf.iter_sections():
    #         if isinstance(section, SymbolTableSection):
    #             for sym in section.iter_symbols():
    #                 if sym.name:
    #                     symbols[sym.name] = sym
    #     return symbols

    # def resolve_file(self, target_file: str):
    #     # Open file
    #     elf_path = os.path.join(build_dir, target_file)
    #     try:
    #         self._elf = ELFFile(open(elf_path, 'rb'))
    #     except FileNotFoundError:
    #         raise RuntimeError(f"ELF file not found: {elf_path}")
    #
    #     dwarf = self._elf.get_dwarf_info()
    #     endian = 'little' if self._elf.little_endian else 'big'
    #     if endian == 'big':
    #         # Note: this will be really trivial to add.
    #         raise NotImplementedError("SDFgen doesn't currently support big "
    #                                   "endian systems for struct generation!")
    #
    #     pointer_size = self._elf.elfclass // 8
    #
    #     typedefs: Dict[str, Any] = None
    #     if dwarf is not None:
    #         typedefs = self._index_dwarf(dwarf)
    #     else:
    #         raise RuntimeError(f"Target file {target_file} doesn't have DWARF symbols!")
    #
    #     symbols = self._index_symbols()


def RegionResourceFactory(map: Map, section_name: Optional[str] = None):
    fields = {
        "vaddr": map.vaddr,
        "size": map.mr.size
    }
    return ConfigStruct("region_resource_t", section_name=section_name, fields=fields)

# TODO: extract to sddf
def DeviceRegionResourceFactory(region: ConfigStruct, io_addr: int):
    fields = {
        "region": region,
        "io_addr": io_addr
    }
    return ConfigStruct("device_region_resource_t", fields=fields)

def DeviceIRQResourceFactory(id: int):
    fields = {
        "id": id
    }
    return ConfigStruct("device_irq_resource_t", fields=fields)

def DeviceResourcesFactory(magic_str: str, maps: List[Map], irq_ids: List[int], target_file: str, section_name = "device_resources"):
    region_structs = [
        DeviceRegionResourceFactory(RegionResourceFactory(m), m.mr.paddr)
        for m in maps
    ]
    irq_structs = [DeviceIRQResourceFactory(i) for i in irq_ids]
    fields = {
        "magic": magic_str,
        "num_regions": len(region_structs),
        "num_irqs": len(irq_structs),
        "regions": region_structs,
        "irqs": irq_structs
    }
    return ConfigStruct("device_resources_t", section_name=section_name, fields=fields, target_file=target_file)
