grammar = r"""
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
