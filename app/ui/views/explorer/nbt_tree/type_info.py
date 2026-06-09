"""NBT Tree type metadata and small UI constants."""

from app.ui.theme import THEME

MAX_DEPTH = 15
MAX_CHILDREN = 100

TYPE_INFO = {
    "Compound": ("📦", "Compound", THEME.accent_light),
    "List": ("📋", "List", THEME.accent_light),
    "String": ("🔤", "String", THEME.terminal_green),
    "Int": ("🔢", "Int", THEME.terminal_cyan),
    "Long": ("🔢", "Long", THEME.terminal_cyan),
    "Byte": ("🔵", "Byte", THEME.terminal_blue),
    "Short": ("🔢", "Short", THEME.terminal_cyan),
    "Float": ("📐", "Float", THEME.terminal_purple),
    "Double": ("📐", "Double", THEME.terminal_purple),
    "IntArray": ("🧮", "IntArray", THEME.warning_light),
    "ByteArray": ("🧮", "ByteArray", THEME.warning_light),
    "str": ("🔤", "String", THEME.terminal_green),
    "int": ("🔢", "Number", THEME.terminal_cyan),
    "float": ("📐", "Number", THEME.terminal_purple),
    "bool": ("🔘", "Boolean", THEME.terminal_blue),
    "NoneType": ("∅", "Null", THEME.text_muted),
    "TAG_Compound": ("📦", "Compound", THEME.accent_light),
    "NBTFile": ("📦", "Compound", THEME.accent_light),
    "TAG_List": ("📋", "List", THEME.accent_light),
    "TAG_String": ("🔤", "String", THEME.terminal_green),
    "TAG_Int": ("🔢", "Int", THEME.terminal_cyan),
    "TAG_Long": ("🔢", "Long", THEME.terminal_cyan),
    "TAG_Byte": ("🔵", "Byte", THEME.terminal_blue),
    "TAG_Short": ("🔢", "Short", THEME.terminal_cyan),
    "TAG_Float": ("📐", "Float", THEME.terminal_purple),
    "TAG_Double": ("📐", "Double", THEME.terminal_purple),
    "TAG_Int_Array": ("🧮", "IntArray", THEME.warning_light),
    "TAG_Byte_Array": ("🧮", "ByteArray", THEME.warning_light),
}

FIELD_TYPE_OPTIONS = [
    "String", "Int", "Long", "Byte", "Short", "Float", "Double",
    "Boolean", "Compound", "List",
]
