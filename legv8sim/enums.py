from enum import IntEnum


class NumberType(IntEnum):
    INTEGER = 0
    SPFLOATINGPOINT = 1
    DPFLOATINGPOINT = 2


class OpToSetFlags(IntEnum):
    ADD = 0
    SUB = 1
    AND = 2
    FCMPS = 3
    FCMPD = 4


class Precision(IntEnum):
    SINGLE = 0
    DOUBLE = 1
