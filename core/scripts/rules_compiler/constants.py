"""Binary format constants and pattern-language limits."""

NONE = 0xFFFFFFFF
NONE16 = 0xFFFF
HEADER_SIZE = 136
MAGIC = b"RDK1"
VERSION = 5

MAX_GAP = 8
MAX_COMBOS = 4096
# `__` wide gap: words and punctuation both count as items
MAX_ANY_SPAN = 32
# punctuation run bounds are packed into one u16 byte each
MAX_PUNCT_RUN = 255

# Largest id storable in a u16 array that reserves 0xFFFF as a sentinel.
U16_MAX_ID = 0xFFFE

# Element kinds (must mirror rdktr_internal.h)
ELEM_WORD = 0
ELEM_PREFIX = 1
ELEM_GAP = 2
ELEM_PUNCT = 3
ELEM_LEXEME = 4
ELEM_PUNCT_RUN = 5
ELEM_ANY = 6
