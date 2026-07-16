"""Binary format constants and pattern-language limits."""

NONE = 0xFFFFFFFF
HEADER_SIZE = 112
MAGIC = b"RDK1"
VERSION = 3

MAX_GAP = 8
MAX_COMBOS = 4096

# Element kinds (must mirror rdktr_internal.h)
ELEM_WORD = 0
ELEM_PREFIX = 1
ELEM_GAP = 2
ELEM_PUNCT = 3
