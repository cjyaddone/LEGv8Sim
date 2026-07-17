import re
import sys

from legv8sim.enums import NumberType
from legv8sim.exceptions import (
    IllegalOpcodeException,
    IncorrectArgumentCountException,
    InvalidConstantException,
    InvalidRegisterException,
    OffsetOutOfRangeException,
    ShamtOutOfRangeException,
)

MAXNUMSHIFT = 64
MAXOFFSET = 256
MAXIMMED = 4096
MAXHALFWORD = 65536

OPCODE_TABLE = {
    "STOP":   (0, 0, 0, 0),
    "NOP":    (1, 0, 0, 0),
    "PUTCHAR": (2, 0, 0, 8),
    "PUTINT": (3, 0, 0, 8),
    "B":      (5, 0, 0, 1),
    "BL":     (37, 0, 0, 18),
    "BR":     (1712, 0, 0, 8),
    "B.EQ":   (84, 0, 0, 1),
    "B.NE":   (84, 0, 1, 1),
    "B.LT":   (84, 0, 11, 1),
    "B.LE":   (84, 0, 13, 1),
    "B.GT":   (84, 0, 12, 1),
    "B.GE":   (84, 0, 10, 1),
    "B.LO":   (84, 0, 3, 1),
    "B.CC":   (84, 0, 3, 1),
    "B.LS":   (84, 0, 9, 1),
    "B.HI":   (84, 0, 8, 1),
    "B.HS":   (84, 0, 2, 1),
    "B.CS":   (84, 0, 2, 1),
    "B.MI":   (84, 0, 4, 1),
    "B.PL":   (84, 0, 5, 1),
    "B.VS":   (84, 0, 6, 1),
    "B.VC":   (84, 0, 7, 1),
    "CBZ":    (180, 0, 0, 2),
    "CBNZ":   (181, 0, 0, 2),
    "STURB":  (448, 0, 0, 3),
    "LDURB":  (450, 0, 0, 3),
    "STURH":  (960, 0, 0, 3),
    "LDURH":  (962, 0, 0, 3),
    "STURW":  (1472, 0, 0, 3),
    "LDURSW": (1476, 0, 0, 3),
    "STXR":   (1600, 0, 0, 5),
    "LDXR":   (1602, 0, 0, 3),
    "STUR":   (1984, 0, 0, 3),
    "LDUR":   (1986, 0, 0, 3),
    "AND":    (1104, 0, 0, 5),
    "ADD":    (1112, 0, 0, 5),
    "ORR":    (1360, 0, 0, 5),
    "EOR":    (1616, 0, 0, 5),
    "SUB":    (1624, 0, 0, 5),
    "ORRI":   (356, 0, 0, 4),
    "EORI":   (420, 0, 0, 4),
    "ADDI":   (580, 0, 0, 4),
    "ANDI":   (584, 0, 0, 4),
    "SUBI":   (836, 0, 0, 4),
    "ADDS":   (1368, 0, 0, 5),
    "ANDS":   (1872, 0, 0, 5),
    "SUBS":   (1880, 0, 0, 5),
    "ADDIS":  (708, 0, 0, 4),
    "SUBIS":  (964, 0, 0, 4),
    "ANDIS":  (968, 0, 0, 4),
    "LSR":    (1690, 0, 0, 6),
    "LSL":    (1691, 0, 0, 6),
    "MOVZ":   (421, 0, 0, 7),
    "MOVK":   (485, 0, 0, 7),
    "MUL":    (1240, 31, 0, 5),
    "UMULH":  (1246, 0, 0, 5),
    "SMULH":  (1242, 0, 0, 5),
    "SDIV":   (1238, 2, 0, 5),
    "UDIV":   (1238, 3, 0, 5),
    "FADDS":  (241, 10, 0, 9),
    "FSUBS":  (241, 14, 0, 9),
    "FCMPS":  (241, 8, 0, 13),
    "FMULS":  (241, 2, 0, 9),
    "FDIVS":  (241, 6, 0, 9),
    "LDURS":  (1506, 0, 0, 11),
    "STURS":  (1504, 0, 0, 11),
    "FADDD":  (243, 10, 0, 10),
    "FSUBD":  (243, 14, 0, 10),
    "FCMPD":  (243, 8, 0, 14),
    "FMULD":  (243, 2, 0, 10),
    "FDIVD":  (243, 6, 0, 10),
    "LDURD":  (2018, 0, 0, 12),
    "STURD":  (2016, 0, 0, 12),
    "CMP":    (1880, 0, 0, 15),
    "CMPI":   (964, 0, 0, 16),
    "MOV":    (1112, 0, 0, 17),
    "LDA":    (581, 0, 0, 2),
}


class Instruction:
    def __init__(self, line_number=0, stalling=False):
        self.opcode = "NOP"
        self.op = 1
        self.opx = 0
        self.cond = 0
        self.format = 0
        self.rA = 31
        self.rB = 31
        self.rC = 31
        self.offset = 0
        self.shamt = 0
        self.target = ""

        # Runtime state (merged from RunTimeInstruction)
        self.is_break = False
        self.stage = ""
        self.line_number = line_number
        self.line_label = ""
        self.target_line_number = -1
        self.stalling = stalling

    def set_fields(self, fields):
        self.opcode = fields[0]
        del fields[0]
        self._parse_opcode()
        self._parse_fields(fields)

    def _parse_opcode(self):
        oc = self.opcode
        entry = OPCODE_TABLE.get(oc)
        if entry is None:
            print(f"Illegal Opcode = {oc}", file=sys.stderr)
            raise IllegalOpcodeException(oc, str(self))
        self.op, self.opx, self.cond, self.format = entry

    def _parse_fields(self, fields):
        f = [""] * 4
        for i, val in enumerate(fields[:4]):
            f[i] = val

        fmt = self.format

        if fmt == 0:
            if len(fields) > 0:
                raise IncorrectArgumentCountException(len(fields), str(self))

        elif fmt in (1, 8, 18):
            if len(fields) != 1:
                raise IncorrectArgumentCountException(len(fields), str(self))
            if fmt == 1:
                self.target = f[0]
            elif fmt == 18:
                self.target = f[0]
                self.rC = 30
            else:
                self.rC = self._get_valid_reg_num(f[0], NumberType.INTEGER)

        elif fmt in (2, 13, 14, 15, 16, 17):
            if len(fields) != 2:
                raise IncorrectArgumentCountException(len(fields), str(self))
            if fmt == 2:
                self.rC = self._get_valid_reg_num(f[0], NumberType.INTEGER)
                self.target = f[1]
            elif fmt == 13:
                self.rA = self._get_valid_reg_num(f[0], NumberType.SPFLOATINGPOINT)
                self.rB = self._get_valid_reg_num(f[1], NumberType.SPFLOATINGPOINT)
            elif fmt == 14:
                self.rA = self._get_valid_reg_num(f[0], NumberType.DPFLOATINGPOINT)
                self.rB = self._get_valid_reg_num(f[1], NumberType.DPFLOATINGPOINT)
            elif fmt == 15:
                self.rA = self._get_valid_reg_num(f[0], NumberType.INTEGER)
                self.rB = self._get_valid_reg_num(f[1], NumberType.INTEGER)
                self.rC = 31
            elif fmt == 16:
                self.rA = self._get_valid_reg_num(f[0], NumberType.INTEGER)
                self.offset = self._get_valid_constant(f[1])
                if self.offset >= 4096 or self.offset < 0:
                    raise OffsetOutOfRangeException(self.offset, str(self))
                self.rC = 31
            elif fmt == 17:
                self.rC = self._get_valid_reg_num(f[0], NumberType.INTEGER)
                self.rA = self._get_valid_reg_num(f[1], NumberType.INTEGER)
                self.rB = 31

        elif fmt in (3, 4, 5, 6, 9, 10, 11, 12):
            if len(fields) != 3:
                raise IncorrectArgumentCountException(len(fields), str(self))
            if fmt in (9, 11):
                self.rC = self._get_valid_reg_num(f[0], NumberType.SPFLOATINGPOINT)
            elif fmt in (10, 12):
                self.rC = self._get_valid_reg_num(f[0], NumberType.DPFLOATINGPOINT)
            else:
                self.rC = self._get_valid_reg_num(f[0], NumberType.INTEGER)

            if fmt == 9:
                self.rA = self._get_valid_reg_num(f[1], NumberType.SPFLOATINGPOINT)
            elif fmt == 10:
                self.rA = self._get_valid_reg_num(f[1], NumberType.DPFLOATINGPOINT)
            else:
                self.rA = self._get_valid_reg_num(f[1], NumberType.INTEGER)

            if fmt == 5:
                self.rB = self._get_valid_reg_num(f[2], NumberType.INTEGER)
            elif fmt == 9:
                self.rB = self._get_valid_reg_num(f[2], NumberType.SPFLOATINGPOINT)
            elif fmt == 10:
                self.rB = self._get_valid_reg_num(f[2], NumberType.DPFLOATINGPOINT)
            else:
                self.offset = self._get_valid_constant(f[2])
                if fmt == 3 and (self.offset >= 256 or self.offset < -256):
                    raise OffsetOutOfRangeException(self.offset, str(self))
                if fmt == 4 and (self.offset >= 4096 or self.offset < 0):
                    raise OffsetOutOfRangeException(self.offset, str(self))
                if fmt == 6:
                    self.shamt = int(self.offset)
                    self.offset = 0
                    if self.shamt >= 64 or self.shamt < 0:
                        raise ShamtOutOfRangeException(self.shamt, str(self))

        elif fmt == 7:
            if len(fields) != 4:
                raise IncorrectArgumentCountException(len(fields), str(self))
            self.rC = self._get_valid_reg_num(f[0], NumberType.INTEGER)
            self.offset = self._get_valid_constant(f[1])
            if self.offset >= 65536 or self.offset < 0:
                raise OffsetOutOfRangeException(self.offset, str(self))
            if f[2] != "LSL":
                raise IllegalOpcodeException(f[2], str(self))
            self.shamt = int(self._get_valid_constant(f[3]))
            if self.shamt not in (0, 16, 32, 48):
                raise ShamtOutOfRangeException(self.shamt, str(self))

    @staticmethod
    def _get_valid_reg_num(reg, number_type):
        if reg == "SP" and number_type == NumberType.INTEGER:
            return 28
        if reg == "FP" and number_type == NumberType.INTEGER:
            return 29
        if reg == "LR" and number_type == NumberType.INTEGER:
            return 30
        if reg == "XZR" and number_type == NumberType.INTEGER:
            return 31
        if reg[0] == 'X' and number_type == NumberType.INTEGER:
            n = int(reg[1:])
            if n < 0 or n > 31:
                raise InvalidRegisterException(reg, "")
            return n
        if reg[0] == 'S' and number_type == NumberType.SPFLOATINGPOINT:
            n = int(reg[1:]) + 32
            if n < 32 or n > 63:
                raise InvalidRegisterException(reg, "")
            return n
        if reg[0] == 'D' and number_type == NumberType.DPFLOATINGPOINT:
            n = int(reg[1:]) + 32
            if n < 32 or n > 63:
                raise InvalidRegisterException(reg, "")
            return n
        raise InvalidRegisterException(reg, "")

    @staticmethod
    def _get_valid_constant(constant):
        if constant[0] != '#' or len(constant) < 2:
            raise InvalidConstantException(constant, "")
        if len(constant) > 2 and constant[1:3] == "0X":
            return int(constant[3:], 16)
        return int(constant[1:])

    def __str__(self):
        return (f"{'T' if self.is_break else 'F'} [{self.line_number:03d}]  "
                f"{self.line_label:12s} "
                f"{self.op:4d} {self.opx:4d} {self.cond:2d} {self.format:2d} "
                f"{self.opcode:8s}  [Rd] {self.rC:2d}  [Rn] {self.rA:2d}  "
                f"[Rm] {self.rB:2d}  [offset] {self.offset:16x}  "
                f"[shamt] {self.shamt:2d}  [target]  {self.target:12s}"
                f" {self.target_line_number:3d}")
