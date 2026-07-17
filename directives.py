from enum import IntEnum


class Directive(IntEnum):
    ASCIIZ = 0
    LONG = 1
    FLOAT = 2
    DOUBLE = 3
    NONE = 4
