import math
import re
import struct
import sys

from legv8sim.instruction import Instruction
from legv8sim.pipeline import InstructionFIFO, ShiftRegister
from legv8sim.directives import Directive
from legv8sim.enums import OpToSetFlags, Precision
from legv8sim.models import BranchTarget, DataLabel
from legv8sim.exceptions import (
    DuplicateLabelException,
    IllegalOpcodeException,
    IncorrectArgumentCountException,
    InvalidConstantException,
    InvalidRegisterException,
    MisalignedDataException,
    NonExistentLabelException,
    NonExistentTargetException,
    OffsetOutOfRangeException,
    ProgramMemoryOutOfRangeException,
    ShamtOutOfRangeException,
)

PROGMEMSIZE = 1024
DATAMEMSIZE = 262144
HEAPBASELINE = 0
MASK64 = 0xFFFFFFFFFFFFFFFF


def _u64(v):
    return v & MASK64


def _s64(v):
    v = v & MASK64
    return v if v < 0x8000000000000000 else v - 0x10000000000000000


def _float_divide(dividend, divisor):
    """Apply default IEEE-754 division behavior instead of Python's zero exception."""
    if divisor != 0.0:
        return dividend / divisor
    if math.isnan(dividend) or dividend == 0.0:
        return math.nan
    sign = math.copysign(1.0, dividend) * math.copysign(1.0, divisor)
    return math.copysign(math.inf, sign)


def _f32_bits(value):
    """Round a Python float to binary32, including overflow to infinity."""
    if math.isnan(value):
        return 0x7FC00000  # Match Java Float.floatToIntBits canonical NaN.
    try:
        return struct.unpack('>I', struct.pack('>f', value))[0]
    except OverflowError:
        infinity = math.copysign(math.inf, value)
        return struct.unpack('>I', struct.pack('>f', infinity))[0]


def _f64_bits(value):
    """Return Java Double.doubleToLongBits-compatible binary64 bits."""
    if math.isnan(value):
        return 0x7FF8000000000000
    return struct.unpack('>Q', struct.pack('>d', value))[0]


class Simulator:
    def __init__(self):
        self.pc = 0
        self.flag_n = False
        self.flag_z = False
        self.flag_v = False
        self.flag_c = False
        self.linecount = 0
        self.need_to_stall = False
        self.need_to_flush = False
        self.need_to_remove_nop = False
        self.line_number_for_nop_to_remove = 0
        self.prog_mem = [Instruction() for _ in range(PROGMEMSIZE)]
        self.inst_fifo = InstructionFIFO()
        self.alu_out_sr = ShiftRegister(2)
        self.input_c_sr = ShiftRegister(2)
        self.dm_out_sr = ShiftRegister(2)
        self.data_mem = [0] * 32768
        self.reg_file = [0] * 64
        self.nop_to_add_list = []
        self.inst_to_replace_list = []
        self.output = ""
        self.target_list = []
        self.label_list = []
        self.breakpoints = set()
        self.exclusive_addr = None
        self._reset_reg_file()
        self._reset_data_mem()
        self._reset_prog_mem()
        self._reset_flags()

    # --- Public accessors ---
    def get_reg(self, index):
        return self.reg_file[index]

    def get_data_mem_word(self, index):
        return self.data_mem[index]

    # --- Reset helpers ---
    def _reset_reg_file(self):
        for i in range(64):
            self.reg_file[i] = 0
        self.reg_file[28] = 262136  # SP
        self.reg_file[29] = 262136  # FP

    def _reset_data_mem(self):
        for i in range(32768):
            self.data_mem[i] = 0
        self.label_list = []

    def _reset_prog_mem(self):
        for i in range(PROGMEMSIZE):
            self.prog_mem[i] = Instruction()
        self.target_list = []
        self.breakpoints = set()
        self.inst_fifo.clear()
        self.alu_out_sr.clear()
        self.input_c_sr.clear()
        self.dm_out_sr.clear()
        self.nop_to_add_list.clear()
        self.inst_to_replace_list.clear()
        self.linecount = 0
        self.pc = 0
        self.need_to_flush = False
        self.need_to_stall = False
        self.exclusive_addr = None

    def _reset_flags(self):
        self.flag_n = False
        self.flag_z = False
        self.flag_v = False
        self.flag_c = False

    def reset_output(self):
        self.output = ""

    def reset_pc(self):
        for rti in self.prog_mem:
            rti.stage = ""
        self.inst_fifo.clear()
        self.alu_out_sr.clear()
        self.input_c_sr.clear()
        self.dm_out_sr.clear()
        self.nop_to_add_list.clear()
        self.inst_to_replace_list.clear()
        self.pc = 0
        self.need_to_flush = False
        self.need_to_stall = False
        self.exclusive_addr = None

    # --- Program loading ---
    @staticmethod
    def _get_fields(line):
        line = line.upper()
        comment_idx = line.find("//")
        if comment_idx > 0:
            line = line[:comment_idx]
        elif comment_idx == 0:
            line = ""
        line = line.strip()
        if not line:
            return []
        # Python's re.split keeps trailing empty strings unlike Java's String.split
        return [x for x in re.split(r"[\s,\[\]]+", line) if x]

    @staticmethod
    def _is_label(s):
        return s.endswith(":")

    def load_prog(self, filepath):
        log = ""
        pending_label = ""
        with open(filepath, 'r') as f:
            for line in f:
                fields = self._get_fields(line)
                if pending_label and fields:
                    fields.insert(0, pending_label)
                if not fields:
                    continue
                if len(fields) == 1 and self._is_label(fields[0]):
                    pending_label = fields[0]
                    continue
                if fields[0] == "":
                    continue
                log += self._log_asm_source_line(fields)
                self._add_instruction(fields)
                pending_label = ""

        for bt in self.target_list:
            target = bt.label
            for i in range(self.linecount):
                if target == self.prog_mem[i].target:
                    self.prog_mem[i].target_line_number = bt.inst_addr

        self.prog_mem[self.linecount] = Instruction(self.linecount)
        self.linecount += 1
        if self.linecount > 0:
            self.prog_mem[0].stage = "IF"
        return log

    @staticmethod
    def _log_asm_source_line(fields):
        result = ""
        idx = 1
        first = fields[0]
        is_lsl = False
        if first.endswith(":"):
            idx = 2
            result += first
        opcode = fields[idx - 1]
        result += "\t" + opcode
        for i in range(idx, len(fields)):
            field = fields[i]
            if i == idx + 2 and opcode == "STXR":
                field = "[" + field + "]"
            elif i == idx + 1 and opcode[:3] in ("LDU", "STU"):
                field = "[" + field
            elif i == idx + 2 and opcode[:3] in ("LDU", "STU"):
                field = field + "]"
            if is_lsl:
                result += " " + field
            else:
                result += "\t" + field if i == idx else ", " + field
            if field == "LSL":
                is_lsl = True
        result += "\n"
        return result

    def _add_instruction(self, fields):
        self.prog_mem[self.linecount] = Instruction()
        first = fields[0]
        if first.endswith(":"):
            label = first[:first.index(':')]
            fields.pop(0)
            bt = BranchTarget(label, self.linecount)
            try:
                self._get_inst_addr(label)
                raise DuplicateLabelException(label)
            except NonExistentTargetException:
                self.target_list.append(bt)
                self.prog_mem[self.linecount].line_label = label
        self.prog_mem[self.linecount].line_number = self.linecount
        self.prog_mem[self.linecount].set_fields(fields)
        self.linecount += 1
        if self.linecount > 1024:
            raise ProgramMemoryOutOfRangeException(self.linecount)

    # --- Data loading ---
    def load_data(self, filepath):
        log = "\n"
        data_log = ""
        addr = 0
        last_addr = 0
        directive = Directive.LONG
        is_label = False
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                tokens = []
                for m in re.finditer(r'"((?:[^\\"]|\\.)*)"|([^,\s"]+)', line):
                    token = m.group(1) if m.group(1) is not None else m.group(2)
                    tokens.append(token)
                for token in tokens:
                    if self._is_label(token):
                        label = token[:token.index(':')].upper()
                        try:
                            self._get_data_addr(label)
                            raise DuplicateLabelException(label)
                        except NonExistentLabelException:
                            dl = DataLabel(label, addr)
                            self.label_list.append(dl)
                            is_label = True
                            continue
                    dir_val = self._asm_directive(token)
                    if dir_val == Directive.NONE:
                        dir_val = directive
                        if dir_val == Directive.ASCIIZ:
                            data_log += f'"{token}"\n'
                            ascii_str = self._ascii_string(token)
                            last_addr = addr
                            chars = list(ascii_str)
                            offset = addr % 8
                            ci = 0
                            i = offset + len(chars)
                            while i > 0:
                                word = self.data_mem[addr >> 3]
                                end = min(i, 8)
                                pos = offset
                                while pos < end:
                                    self.data_mem[addr >> 3] = _u64((word & self._byte_mask(pos)) | (ord(chars[ci]) << (8 * pos)))
                                    word = self.data_mem[addr >> 3]
                                    pos += 1
                                    ci += 1
                                    addr += 1
                                offset = 0
                                i -= 8

                        elif dir_val == Directive.LONG:
                            if len(token) > 2 and token[:2].upper() == "0X":
                                val = int(token[2:], 16)
                            else:
                                val = int(token)
                            if addr % 8 != 0:
                                addr = ((addr >> 3) + 1) << 3
                            self.data_mem[addr >> 3] = _u64(val)
                            last_addr = addr
                            addr += 8
                            data_log += f"{val}\n"

                        elif dir_val == Directive.FLOAT:
                            if len(token) > 2 and token[:2].upper() == "0X":
                                bits = int(token[2:], 16)
                                f_val = struct.unpack('>f', struct.pack('>I', bits))[0]
                            else:
                                f_val = float(token)
                            if addr % 4 != 0:
                                addr = ((addr >> 2) + 1) << 2
                            bits = struct.unpack('>I', struct.pack('>f', f_val))[0]
                            if addr % 8 == 0:
                                self.data_mem[addr >> 3] = _u64((bits & self._word_mask(0)) | (self.data_mem[addr >> 3] & self._word_mask(4)))
                            else:
                                self.data_mem[addr >> 3] = _u64((bits << 32) | (self.data_mem[addr >> 3] & self._word_mask(0)))
                            last_addr = addr
                            addr += 4
                            data_log += f"{f_val}\n"

                        elif dir_val == Directive.DOUBLE:
                            if len(token) > 2 and token[:2].upper() == "0X":
                                bits = int(token[2:], 16)
                                d_val = struct.unpack('>d', struct.pack('>Q', bits))[0]
                            else:
                                d_val = float(token)
                            if addr % 8 != 0:
                                addr = ((addr >> 3) + 1) << 3
                            self.data_mem[addr >> 3] = struct.unpack('>Q', struct.pack('>d', d_val))[0]
                            last_addr = addr
                            addr += 8
                            data_log += f"{d_val}\n"

                        if is_label:
                            dl = self.label_list[-1]
                            dl.data_addr = last_addr
                            is_label = False
                        continue
                    directive = dir_val

        data_log += "\n"
        for dl in self.label_list:
            data_log += f"{dl.label}:\t{dl.data_addr:05x}\n"
        return data_log

    def _reset_data_mem(self):
        for i in range(32768):
            self.data_mem[i] = 0
        self.label_list = []

    # --- Step ---
    def step(self, pipelined):
        n = self.pc
        result = str(self.prog_mem[n])
        reg_c = 0

        if pipelined:
            if self.need_to_remove_nop:
                val = self.line_number_for_nop_to_remove
                if val in self.nop_to_add_list:
                    self.nop_to_add_list.remove(val)
                self.need_to_remove_nop = False

            rti_ifid = self.inst_fifo.ifid()
            rti_idex = self.inst_fifo.idex()
            rti_exdm = self.inst_fifo.exdm()
            rti_dmwb = self.inst_fifo.dmwb()

            if rti_ifid is not None:
                line_num = rti_ifid.line_number
                self.need_to_stall = self.inst_fifo.need_to_stall()
                if not rti_ifid.stalling:
                    self.prog_mem[line_num].stage = "ID" if self.need_to_stall else "EX"
                if self.need_to_flush:
                    print(f"Instruction @ ID [{line_num:2d}] = {rti_ifid.opcode} *** flushed ***")
                    self.inst_fifo.set_ifid(Instruction(line_num))
                    self.inst_to_replace_list.append(line_num)
                    rti_ifid = self.inst_fifo.ifid()
                    self.need_to_flush = False
                elif self.need_to_stall:
                    print(f"Instruction @ ID [{line_num:2d}] = {rti_ifid.opcode} *** stalling ***")
                    self.inst_fifo.set_ifid(Instruction(line_num, stalling=True))
                    self.nop_to_add_list.append(line_num)
                    rti_ifid = self.inst_fifo.ifid()
                    self.prog_mem[n].stage = ""
                    self.pc = line_num
                else:
                    print(f"Instruction @ ID [{line_num:2d}] = {rti_ifid.opcode}")
                reg_c = self.reg_file[rti_ifid.rC]

            if rti_idex is not None:
                if not rti_idex.stalling:
                    self.prog_mem[rti_idex.line_number].stage = "EX" if self.need_to_stall else "DM"
                ra = self.reg_file[rti_idex.rA]
                rb = self.reg_file[rti_idex.rB]
                rc = self.reg_file[rti_idex.rC]

                haz = self.inst_fifo.raw_rf_data_hazard_at(1)
                if haz == rti_idex.rA and rti_idex.rA != 31:
                    ra = self.alu_out_sr.get_at(0)
                else:
                    haz = self.inst_fifo.raw_dm_data_hazard_at(1)
                    if haz == rti_idex.rA and rti_idex.rA != 31:
                        ra = self.dm_out_sr.get_at(0)

                haz = self.inst_fifo.raw_rf_data_hazard_at(2)
                if haz == rti_idex.rB and rti_idex.rB != 31:
                    rb = self.alu_out_sr.get_at(0)
                else:
                    haz = self.inst_fifo.raw_dm_data_hazard_at(2)
                    if haz == rti_idex.rB and rti_idex.rB != 31:
                        rb = self.dm_out_sr.get_at(0)

                haz = self.inst_fifo.raw_rf_data_hazard_at(3)
                if haz == rti_idex.rC and rti_idex.rC != 31:
                    rc = self.alu_out_sr.get_at(0)
                else:
                    haz = self.inst_fifo.raw_dm_data_hazard_at(3)
                    if haz == rti_idex.rC and rti_idex.rC != 31:
                        rc = self.dm_out_sr.get_at(0)

                alu_result = self._execute(rti_idex, ra, rb, rc)
                if not self.need_to_stall:
                    self.alu_out_sr.insert(alu_result)
                    self.input_c_sr.insert(ra if rti_idex.op == 1600 else rc)

            if rti_exdm is not None:
                if not rti_exdm.stalling:
                    self.prog_mem[rti_exdm.line_number].stage = "DM" if self.need_to_stall else "WB"
                idx = 0 if self.need_to_stall else 1
                alu_out = self.alu_out_sr.get_at(idx)
                input_c = self.input_c_sr.get_at(idx)
                mem_result = self._access_dm(rti_exdm, alu_out, input_c)
                if not self.need_to_stall:
                    self.dm_out_sr.insert(mem_result)

            if rti_dmwb is not None:
                if not rti_dmwb.stalling:
                    self.prog_mem[rti_dmwb.line_number].stage = "WB" if self.need_to_stall else "IF"
                idx = 0 if self.need_to_stall else 1
                wb_data = self.dm_out_sr.get_at(idx)
                self._write_rf(rti_dmwb, wb_data)
                if rti_dmwb.op == 1 and rti_dmwb.stalling:
                    self.need_to_remove_nop = True
                    self.line_number_for_nop_to_remove = rti_dmwb.line_number

            if rti_ifid is not None:
                if not self.need_to_stall:
                    haz = self.inst_fifo.ex_reg_branch_hazard_at()
                    if haz == rti_ifid.rC and rti_ifid.rC != 31:
                        reg_c = self.alu_out_sr.get_at(0)
                        print(f"*** EXRegBranch Hazard @ R{haz}\tALUOut = {reg_c:x}")
                    else:
                        haz = self.inst_fifo.dm_reg_branch_hazard_at()
                        if haz == rti_ifid.rC and rti_ifid.rC != 31:
                            reg_c = self.dm_out_sr.get_at(0)
                            print(f"*** DMRegBranch Hazard @ R{haz}\tDMOut = {reg_c:x}")
                        else:
                            haz = self.inst_fifo.wb_reg_branch_hazard_at()
                            if haz == rti_ifid.rC and rti_ifid.rC != 31:
                                reg_c = self.dm_out_sr.get_at(1)
                                print(f"*** WBRegBranch Hazard @ R{haz}\tRFIn = {reg_c:x}")
                    self.pc = self._next_pc(n, rti_ifid, reg_c)
                    if self.pc in self.inst_to_replace_list:
                        self.inst_to_replace_list.remove(self.pc)
            else:
                self.pc = self._next_pc(n, None, 0)

            if not self.need_to_stall:
                displaced = self.inst_fifo.insert(self.prog_mem[n])
                self.prog_mem[n].stage = "ID"
                if displaced is not None:
                    if displaced.line_number in self.inst_to_replace_list:
                        self.inst_to_replace_list.remove(displaced.line_number)
                    self.prog_mem[displaced.line_number].stage = ""
            self.prog_mem[self.pc].stage = "IF"
        else:
            # Single-cycle mode
            rti = self.prog_mem[n]
            ra = self.reg_file[rti.rA]
            rb = self.reg_file[rti.rB]
            rc = self.reg_file[rti.rC]
            alu_result = self._execute(rti, ra, rb, rc)
            store_data = ra if rti.op == 1600 else rc
            mem_result = self._access_dm(rti, alu_result, store_data)
            self._write_rf(rti, mem_result)
            self.pc = self._next_pc(n, rti, rc)

        return result

    # --- Execute ---
    def _execute(self, rti, ra, rb, rc):
        ra = _u64(ra)
        rb = _u64(rb)
        rc = _u64(rc)
        result = 0
        op = rti.op

        if op == 0:    # STOP
            pass
        elif op == 1:  # NOP
            pass
        elif op == 2:  # PUTCHAR
            result = rc
        elif op == 3:  # PUTINT
            result = rc
        elif op == 5:  # B
            pass
        elif op == 37:  # BL
            result = _u64(rti.line_number + 1)
        elif op == 1712:  # BR
            result = rc
        elif op == 84:  # B.cond
            pass
        elif op == 180:  # CBZ
            pass
        elif op == 181:  # CBNZ
            pass
        # R-format ALU
        elif op == 1112: result = _u64(ra + rb)       # ADD
        elif op == 1624: result = _u64(ra - rb)       # SUB
        elif op == 1360: result = ra | rb             # ORR
        elif op == 1104: result = ra & rb             # AND
        elif op == 1616: result = ra ^ rb             # EOR
        # I-format ALU
        elif op == 580:  result = _u64(ra + rti.offset)    # ADDI
        elif op == 836:  result = _u64(ra - rti.offset)    # SUBI
        elif op == 356:  result = ra | rti.offset          # ORRI
        elif op == 584:  result = ra & rti.offset          # ANDI
        elif op == 420:  result = ra ^ rti.offset          # EORI
        # R-format with flags
        elif op == 1368: result = _u64(ra + rb); self._set_flags(result, ra, rb, OpToSetFlags.ADD)   # ADDS
        elif op == 1880: result = _u64(ra - rb); self._set_flags(result, ra, rb, OpToSetFlags.SUB)   # SUBS
        elif op == 1872: result = ra & rb; self._set_flags(result, ra, rb, OpToSetFlags.AND)         # ANDS
        # I-format with flags
        elif op == 708:  # ADDIS
            imm = rti.offset
            result = _u64(ra + imm)
            self._set_flags(result, ra, imm, OpToSetFlags.ADD)
        elif op == 964:  # SUBIS
            imm = rti.offset
            result = _u64(ra - imm)
            self._set_flags(result, ra, imm, OpToSetFlags.SUB)
        elif op == 968:  # ANDIS
            imm = rti.offset
            result = ra & imm
            self._set_flags(result, ra, imm, OpToSetFlags.AND)
        # Load/Store address computation
        elif op in (1986, 2018, 1506, 1476, 962, 450, 1602):
            result = _u64(ra + rti.offset)
        elif op in (1984, 2016, 1472, 1504, 960, 448):
            result = _u64(ra + rti.offset)
        elif op == 1600:  # STXR: Rm is the address register
            result = rb
        # Shifts
        elif op == 1691: result = _u64(ra << rti.shamt)   # LSL
        elif op == 1690: result = _u64(ra >> rti.shamt)   # LSR
        # Moves
        elif op == 421:  # MOVZ
            result = _u64(rti.offset << rti.shamt)
        elif op == 485:  # MOVK
            lane_mask = 0xFFFF << rti.shamt
            result = _u64((rc & ~lane_mask) | (rti.offset << rti.shamt))
        # Multiply/Divide
        elif op == 1240:  # MUL
            result = _u64(ra * rb)
        elif op == 1246:  # UMULH
            result = _u64((ra * rb) >> 64)
        elif op == 1242:  # SMULH
            result = _u64((_s64(ra) * _s64(rb)) >> 64)
        elif op == 1238:  # SDIV/UDIV
            if rb == 0:
                result = 0
            elif rti.opx == 2:  # SDIV: truncate toward zero
                dividend = _s64(ra)
                divisor = _s64(rb)
                quotient = abs(dividend) // abs(divisor)
                result = _u64(-quotient if (dividend < 0) != (divisor < 0) else quotient)
            elif rti.opx == 3:
                result = _u64(ra // rb)  # UDIV
        # FP single
        elif op == 241:
            f1 = struct.unpack('>f', struct.pack('>I', int(ra) & 0xFFFFFFFF))[0]
            f2 = struct.unpack('>f', struct.pack('>I', int(rb) & 0xFFFFFFFF))[0]
            if rti.opx == 10:   # FADDS
                bits = _f32_bits(f1 + f2)
                result = _u64(bits)
                self._check_fp_out_of_range(result, ra, rb, Precision.SINGLE)
            elif rti.opx == 14:  # FSUBS
                bits = _f32_bits(f1 - f2)
                result = _u64(bits)
                self._check_fp_out_of_range(result, ra, rb, Precision.SINGLE)
            elif rti.opx == 2:   # FMULS
                bits = _f32_bits(f1 * f2)
                result = _u64(bits)
                self._check_fp_out_of_range(result, ra, rb, Precision.SINGLE)
            elif rti.opx == 6:   # FDIVS
                bits = _f32_bits(_float_divide(f1, f2))
                result = _u64(bits)
                self._check_fp_out_of_range(result, ra, rb, Precision.SINGLE)
            elif rti.opx == 8:   # FCMPS
                self._set_flags(0, ra, rb, OpToSetFlags.FCMPS)
        # FP double
        elif op == 243:
            d1 = struct.unpack('>d', struct.pack('>Q', ra))[0]
            d2 = struct.unpack('>d', struct.pack('>Q', rb))[0]
            if rti.opx == 10:   # FADDD
                result = _f64_bits(d1 + d2)
                self._check_fp_out_of_range(result, ra, rb, Precision.DOUBLE)
            elif rti.opx == 14:  # FSUBD
                result = _f64_bits(d1 - d2)
                self._check_fp_out_of_range(result, ra, rb, Precision.DOUBLE)
            elif rti.opx == 2:   # FMULD
                result = _f64_bits(d1 * d2)
                self._check_fp_out_of_range(result, ra, rb, Precision.DOUBLE)
            elif rti.opx == 6:   # FDIVD
                result = _f64_bits(_float_divide(d1, d2))
                self._check_fp_out_of_range(result, ra, rb, Precision.DOUBLE)
            elif rti.opx == 8:   # FCMPD
                self._set_flags(0, ra, rb, OpToSetFlags.FCMPD)
        # LDA
        elif op == 581:  # LDA
            result = self._get_data_addr(rti.target)

        return _u64(result)

    # --- Data memory access ---
    def _access_dm(self, rti, addr, store_data):
        ea = int(_u64(addr))
        result = 0
        op = rti.op

        if op in (0, 1, 5, 84, 180, 181, 1712):
            pass
        elif op in (2, 3, 37):
            result = addr
        # ALU ops that pass through
        elif op in (1112, 1624, 1360, 1104, 1616, 580, 836, 356, 584, 420,
                    1368, 1880, 1872, 708, 964, 968, 1691, 1690, 421, 485,
                    1240, 1246, 1242, 1238, 241, 243, 581):
            result = addr
        # LDUR / LDURD
        elif op in (1986, 2018):
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 8 != 0:
                raise MisalignedDataException(ea, str(rti))
            result = self.data_mem[ea >> 3]
        # LDURS
        elif op == 1506:
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 4 != 0:
                raise MisalignedDataException(ea, str(rti))
            shift = 4 - ea % 8
            result = _u64(_u64(self.data_mem[ea >> 3] << (8 * shift)) >> 32)
        # LDURSW (signed word load)
        elif op == 1476:
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 4 != 0:
                raise MisalignedDataException(ea, str(rti))
            shift = 4 - ea % 8
            result = _u64(_s64(self.data_mem[ea >> 3] << (8 * shift)) >> 32)
        # LDURH
        elif op == 962:
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 2 != 0:
                raise MisalignedDataException(ea, str(rti))
            shift = 6 - ea % 8
            result = _u64(_u64(self.data_mem[ea >> 3] << (8 * shift)) >> 48)
        # LDURB
        elif op == 450:
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            shift = 7 - ea % 8
            result = _u64(_u64(self.data_mem[ea >> 3] << (8 * shift)) >> 56)
        # LDXR
        elif op == 1602:
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 8 != 0:
                raise MisalignedDataException(ea, str(rti))
            result = self.data_mem[ea >> 3]
            self.exclusive_addr = ea
        # STUR / STURD
        elif op in (1984, 2016):
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 8 != 0:
                raise MisalignedDataException(ea, str(rti))
            self.data_mem[ea >> 3] = _u64(store_data)
        # STURW / STURS
        elif op in (1472, 1504):
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 4 != 0:
                raise MisalignedDataException(ea, str(rti))
            offset = ea % 8
            self.data_mem[ea >> 3] = _u64(
                (self.data_mem[ea >> 3] & self._word_mask(offset)) |
                ((store_data & 0xFFFFFFFF) << (8 * offset))
            )
        # STURH
        elif op == 960:
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 2 != 0:
                raise MisalignedDataException(ea, str(rti))
            offset = ea % 8
            self.data_mem[ea >> 3] = _u64(
                (self.data_mem[ea >> 3] & self._half_word_mask(offset)) |
                ((store_data & 0xFFFF) << (8 * offset))
            )
        # STURB
        elif op == 448:
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            offset = ea % 8
            self.data_mem[ea >> 3] = _u64(
                (self.data_mem[ea >> 3] & self._byte_mask(offset)) |
                ((store_data & 0xFF) << (8 * offset))
            )
        # STXR
        elif op == 1600:
            if ea >= DATAMEMSIZE or ea < 0:
                raise IndexError(f"LEGISS: data memory address 0x{ea:05x} out of bounds in\n\t{rti}")
            if ea % 8 != 0:
                raise MisalignedDataException(ea, str(rti))
            if self.exclusive_addr == ea:
                self.data_mem[ea >> 3] = _u64(store_data)
                result = 0
            else:
                result = 1
            self.exclusive_addr = None

        return _u64(result)

    # --- Write register file ---
    def _write_rf(self, rti, data):
        data = _u64(data)
        self.reg_file[31] = 0
        op = rti.op

        if op in (0, 1):  # STOP, NOP
            pass
        elif op == 2:  # PUTCHAR
            self.output += chr(int(data) & 0xFFFF)
        elif op == 3:  # PUTINT
            self.output += str(_s64(data))
        elif op in (5, 1712, 84, 180, 181):  # Branches
            pass
        elif op in (1112, 1624, 1360, 1104, 1616, 1368, 1880, 1872):  # R-format ALU
            self.reg_file[rti.rC] = data
        elif op in (580, 836, 356, 584, 420, 708, 964, 968):  # I-format ALU
            self.reg_file[rti.rC] = data
        elif op in (1986, 2018, 1506, 1476, 962, 450, 1602):  # Loads
            self.reg_file[rti.rC] = data
        elif op in (1984, 2016, 1472, 1504, 960, 448):  # Stores (no writeback)
            pass
        elif op == 1600:  # STXR
            self.reg_file[rti.rC] = data
        elif op in (1691, 1690, 421, 485):  # Shifts, Moves
            self.reg_file[rti.rC] = data
        elif op in (1240, 1246, 1242, 1238):  # Mul/Div
            self.reg_file[rti.rC] = data
        elif op in (241, 243):  # FP
            self.reg_file[rti.rC] = data
        elif op in (37, 581):  # BL, LDA
            self.reg_file[rti.rC] = data
        else:
            self.reg_file[rti.rC] = data

        self.reg_file[31] = 0

    # --- Next PC ---
    def _next_pc(self, current_pc, rti, reg_val):
        reg_val = _u64(reg_val)
        branch = False
        next_pc = current_pc + 1
        if rti is None:
            return next_pc

        op = rti.op
        if op == 5:    # B
            branch = True
        elif op == 37:  # BL
            branch = True
        elif op == 84:  # B.cond
            cond = rti.cond
            if cond == 0:   branch = self.flag_z
            elif cond == 1: branch = not self.flag_z
            elif cond == 11: branch = self.flag_n != self.flag_v
            elif cond == 13: branch = self.flag_z or (self.flag_n != self.flag_v)
            elif cond == 12: branch = (not self.flag_z) and (self.flag_n == self.flag_v)
            elif cond == 10: branch = self.flag_n == self.flag_v
            elif cond == 3:  branch = not self.flag_c
            elif cond == 9:  branch = self.flag_z or (not self.flag_c)
            elif cond == 8:  branch = (not self.flag_z) and self.flag_c
            elif cond == 2:  branch = self.flag_c
            elif cond == 4:  branch = self.flag_n
            elif cond == 5:  branch = not self.flag_n
            elif cond == 6:  branch = self.flag_v
            elif cond == 7:  branch = not self.flag_v
        elif op == 180:  # CBZ
            branch = reg_val == 0
        elif op == 181:  # CBNZ
            branch = reg_val != 0

        if op == 0:  # STOP
            next_pc = current_pc
            self.need_to_flush = True
        elif op == 1712:  # BR
            next_pc = int(reg_val % (1 << 64))
            self.need_to_flush = True
        elif branch:
            next_pc = self._get_inst_addr(rti.target)
            self.need_to_flush = True

        return next_pc

    # --- Label resolution ---
    def _get_inst_addr(self, target):
        for bt in self.target_list:
            if bt.label == target:
                return bt.inst_addr
        raise NonExistentTargetException(target)

    def _get_data_addr(self, label):
        for dl in self.label_list:
            if dl.label == label:
                return dl.data_addr
        raise NonExistentLabelException(label)

    # --- Run ---
    def run(self, pipelined):
        while True:
            self.step(pipelined)
            if self._is_stop(self.pc, pipelined) or self.pc in self.breakpoints:
                break
        if self._is_stop(self.pc, pipelined) and pipelined:
            for _ in range(6):
                self.step(pipelined)

    def _is_stop(self, pc, pipelined):
        if pipelined:
            rti = self.inst_fifo.ifid()
            return rti is not None and rti.op == 1 and self.prog_mem[pc].op == 0
        return self.prog_mem[pc].op == 0

    # --- Memory mask helpers ---
    @staticmethod
    def _byte_mask(n):
        masks = {
            0: -256,              # 0xFFFFFFFFFFFFFF00
            1: -65281,            # 0xFFFFFFFFFFFF00FF
            2: -16711681,         # 0xFFFFFFFFFF00FFFF
            3: -4278190081,       # 0xFFFFFFFF00FFFFFF
            4: -1095216660481,    # 0xFFFFFF00FFFFFFFF
            5: -280375465082881,  # 0xFFFF00FFFFFFFFFF
            6: -71776119061217281, # 0xFF00FFFFFFFFFFFF
            7: 0xFFFFFFFFFFFFFF,  # 0x00FFFFFFFFFFFFFF  -- note: Java code has 0xFFFFFFFFFFFFFFL not a negative number here
        }
        return _u64(masks.get(n, MASK64))

    @staticmethod
    def _half_word_mask(n):
        masks = {
            0: -65536,              # 0xFFFFFFFFFFFF0000
            2: -4294901761,         # 0xFFFFFFFF0000FFFF
            4: -281470681743361,    # 0xFFFF0000FFFFFFFF
            6: 0xFFFFFFFFFFFF,      # 0x0000FFFFFFFFFFFF
        }
        return _u64(masks.get(n, MASK64))

    @staticmethod
    def _word_mask(n):
        masks = {
            0: -4294967296,  # 0xFFFFFFFF00000000
            4: 0xFFFFFFFF,   # 0x00000000FFFFFFFF
        }
        return _u64(masks.get(n, MASK64))

    # --- FP helpers ---
    @staticmethod
    def _check_fp_out_of_range(result, op_a, op_b, precision):
        result = _u64(result)
        op_a = _u64(op_a)
        op_b = _u64(op_b)
        a_pos_inf = a_neg_inf = a_nan = False
        b_pos_inf = b_neg_inf = b_nan = False
        c_pos_inf = c_neg_inf = c_nan = False

        if precision == Precision.SINGLE:
            exp_a = (int(op_a) & 0xFF800000) >> 23
            exp_b = (int(op_b) & 0xFF800000) >> 23
            exp_c = (int(result) & 0xFF800000) >> 23
            man_a = int(op_a) & 0x7FFFFF
            man_b = int(op_b) & 0x7FFFFF
            man_c = int(result) & 0x7FFFFF
            print(f"S/Exp A = {exp_a:03x}  Mantissa A = {man_a:06x}")
            print(f"S/Exp B = {exp_b:03x}  Mantissa B = {man_b:06x}")
            print(f"S/Exp C = {exp_c:03x}  Mantissa C = {man_c:06x}")
            a_pos_inf = exp_a == 255 and man_a == 0
            a_neg_inf = exp_a == 511 and man_a == 0
            a_nan = (exp_a == 255 or exp_a == 511) and man_a != 0
            b_pos_inf = exp_b == 255 and man_b == 0
            b_neg_inf = exp_b == 511 and man_b == 0
            b_nan = (exp_b == 255 or exp_b == 511) and man_b != 0
            c_pos_inf = exp_c == 255 and man_c == 0
            c_neg_inf = exp_c == 511 and man_c == 0
            c_nan = (exp_c == 255 or exp_c == 511) and man_c != 0
        elif precision == Precision.DOUBLE:
            exp_a = (op_a & 0xFFF0000000000000) >> 52
            exp_b = (op_b & 0xFFF0000000000000) >> 52
            exp_c = (result & 0xFFF0000000000000) >> 52
            man_a = op_a & 0xFFFFFFFFFFFFF
            man_b = op_b & 0xFFFFFFFFFFFFF
            man_c = result & 0xFFFFFFFFFFFFF
            print(f"S/Exp A = {exp_a:03x}  Mantissa A = {man_a:013x}")
            print(f"S/Exp B = {exp_b:03x}  Mantissa B = {man_b:013x}")
            print(f"S/Exp C = {exp_c:03x}  Mantissa C = {man_c:013x}")
            a_pos_inf = exp_a == 2047 and man_a == 0
            a_neg_inf = exp_a == 4095 and man_a == 0
            a_nan = (exp_a == 2047 or exp_a == 4095) and man_a != 0
            b_pos_inf = exp_b == 2047 and man_b == 0
            b_neg_inf = exp_b == 4095 and man_b == 0
            b_nan = (exp_b == 2047 or exp_b == 4095) and man_b != 0
            c_pos_inf = exp_c == 2047 and man_c == 0
            c_neg_inf = exp_c == 4095 and man_c == 0
            c_nan = (exp_c == 2047 or exp_c == 4095) and man_c != 0

        if a_pos_inf: print("A = +INFINITY")
        elif a_neg_inf: print("A = -INFINITY")
        elif a_nan: print("A = NaN")
        if b_pos_inf: print("B = +INFINITY")
        elif b_neg_inf: print("B = -INFINITY")
        elif b_nan: print("B = NaN")
        if c_pos_inf: print("C = +INFINITY")
        elif c_neg_inf: print("C = -INFINITY")
        elif c_nan: print("C = NaN")

    # --- Set flags ---
    def _set_flags(self, result, op_a, op_b, op_type):
        result = _u64(result)
        op_a = _u64(op_a)
        op_b = _u64(op_b)
        self.flag_n = False
        self.flag_z = False
        self.flag_v = False
        self.flag_c = False

        if op_type == OpToSetFlags.FCMPS:
            f1 = struct.unpack('>f', struct.pack('>I', int(op_a) & 0xFFFFFFFF))[0]
            f2 = struct.unpack('>f', struct.pack('>I', int(op_b) & 0xFFFFFFFF))[0]
            exp_a = (int(op_a) & 0xFF800000) >> 23
            exp_b = (int(op_b) & 0xFF800000) >> 23
            man_a = int(op_a) & 0x7FFFFF
            man_b = int(op_b) & 0x7FFFFF
            a_pos_inf = exp_a == 255 and man_a == 0
            a_neg_inf = exp_a == 511 and man_a == 0
            a_nan = (exp_a == 255 or exp_a == 511) and man_a != 0
            b_pos_inf = exp_b == 255 and man_b == 0
            b_neg_inf = exp_b == 511 and man_b == 0
            b_nan = (exp_b == 255 or exp_b == 511) and man_b != 0
            if not a_nan and not b_nan:
                self.flag_n = f1 < f2
                self.flag_z = f1 == f2
                self.flag_c = f1 >= f2
            else:
                self.flag_v = True
                self.flag_c = True
        elif op_type == OpToSetFlags.FCMPD:
            d1 = struct.unpack('>d', struct.pack('>Q', op_a))[0]
            d2 = struct.unpack('>d', struct.pack('>Q', op_b))[0]
            exp_a = (op_a & 0xFFF0000000000000) >> 52
            exp_b = (op_b & 0xFFF0000000000000) >> 52
            man_a = op_a & 0xFFFFFFFFFFFFF
            man_b = op_b & 0xFFFFFFFFFFFFF
            a_pos_inf = exp_a == 2047 and man_a == 0
            a_neg_inf = exp_a == 4095 and man_a == 0
            a_nan = (exp_a == 2047 or exp_a == 4095) and man_a != 0
            b_pos_inf = exp_b == 2047 and man_b == 0
            b_neg_inf = exp_b == 4095 and man_b == 0
            b_nan = (exp_b == 2047 or exp_b == 4095) and man_b != 0
            if not a_nan and not b_nan:
                self.flag_n = d1 < d2
                self.flag_z = d1 == d2
                self.flag_c = d1 >= d2
            else:
                self.flag_v = True
                self.flag_c = True
        else:
            s_result = _s64(result)
            self.flag_n = s_result < 0
            self.flag_z = result == 0

        if op_type == OpToSetFlags.ADD:
            self.flag_v = (_s64(op_a) >= 0 and _s64(op_b) >= 0 and _s64(result) < 0) or \
                          (_s64(op_a) < 0 and _s64(op_b) < 0 and _s64(result) >= 0)
        elif op_type == OpToSetFlags.SUB:
            self.flag_v = (_s64(op_a) >= 0 and _s64(op_b) < 0 and _s64(result) < 0) or \
                          (_s64(op_a) < 0 and _s64(op_b) >= 0 and _s64(result) >= 0)
        elif op_type == OpToSetFlags.AND:
            self.flag_v = False

        if op_type == OpToSetFlags.ADD:
            self.flag_c = (result & MASK64) < (op_b & MASK64)
        elif op_type == OpToSetFlags.SUB:
            self.flag_c = (op_a & MASK64) >= (op_b & MASK64)
        elif op_type == OpToSetFlags.AND:
            self.flag_c = False

    # --- Directive parsing ---
    @staticmethod
    def _asm_directive(s):
        s = s.lower()
        if s == ".asciiz":
            return Directive.ASCIIZ
        elif s == ".long":
            return Directive.LONG
        elif s == ".float":
            return Directive.FLOAT
        elif s == ".double":
            return Directive.DOUBLE
        return Directive.NONE

    @staticmethod
    def _ascii_string(s):
        s = s.replace("\\t", "\t")
        s = s.replace("\\n", "\n")
        s = s.replace('\\"', '"')
        s = s + '\0'
        return s

    def get_output(self):
        return self.output

    # --- Dump formatting ---
    def dump_reg_file(self):
        nl = "\n"
        reg = self.reg_file
        sb = []
        sb.append(f"X00-X07:  {reg[0]:016x}  {reg[1]:016x}  {reg[2]:016x}  {reg[3]:016x}  {reg[4]:016x}  {reg[5]:016x}  {reg[6]:016x}  {reg[7]:016x}")
        sb.append(nl)
        sb.append(f"X08-X15:  {reg[8]:016x}  {reg[9]:016x}  {reg[10]:016x}  {reg[11]:016x}  {reg[12]:016x}  {reg[13]:016x}  {reg[14]:016x}  {reg[15]:016x}")
        sb.append(nl)
        sb.append(f"X16-X23:  {reg[16]:016x}  {reg[17]:016x}  {reg[18]:016x}  {reg[19]:016x}  {reg[20]:016x}  {reg[21]:016x}  {reg[22]:016x}  {reg[23]:016x}")
        sb.append(nl)
        sb.append(f"X24-X31:  {reg[24]:016x}  {reg[25]:016x}  {reg[26]:016x}  {reg[27]:016x}  {reg[28]:016x}  {reg[29]:016x}  {reg[30]:016x}  {reg[31]:016x}")
        sb.append(nl)
        sb.append(f"     PC:  {self.pc:016x}  NZVC              {1 if self.flag_n else 0}{1 if self.flag_z else 0}{1 if self.flag_v else 0}{1 if self.flag_c else 0}                                SP                FP                LR")
        sb.append(nl)
        sb.append(f"F00-F07:  {reg[32]:016x}  {reg[33]:016x}  {reg[34]:016x}  {reg[35]:016x}  {reg[36]:016x}  {reg[37]:016x}  {reg[38]:016x}  {reg[39]:016x}")
        sb.append(nl)
        sb.append(f"F08-F15:  {reg[40]:016x}  {reg[41]:016x}  {reg[42]:016x}  {reg[43]:016x}  {reg[44]:016x}  {reg[45]:016x}  {reg[46]:016x}  {reg[47]:016x}")
        sb.append(nl)
        sb.append(f"F16-F23:  {reg[48]:016x}  {reg[49]:016x}  {reg[50]:016x}  {reg[51]:016x}  {reg[52]:016x}  {reg[53]:016x}  {reg[54]:016x}  {reg[55]:016x}")
        sb.append(nl)
        sb.append(f"F24-F31:  {reg[56]:016x}  {reg[57]:016x}  {reg[58]:016x}  {reg[59]:016x}  {reg[60]:016x}  {reg[61]:016x}  {reg[62]:016x}  {reg[63]:016x}")
        sb.append(nl)
        return "".join(sb).upper()

    def dump_data_mem(self, start):
        nl = "\n"
        addr = (start >> 6) << 6
        sb = []
        for i in range(16):
            sb.append(f"D[{addr:05x}]:")
            for j in range(8):
                if addr < DATAMEMSIZE:
                    sb.append(f"  {self.data_mem[addr >> 3]:016x}")
                addr += 8
            sb.append(nl)
        return "".join(sb).upper()

    def dump_stack(self, start):
        nl = "\n"
        addr = (start >> 6) << 6
        sb = []
        for i in range(16):
            sb.append(f"D[{addr:05x}]:")
            for j in range(8):
                if addr > 0:
                    sb.append(f"  {self.data_mem[addr >> 3]:016x}")
                addr += 8
            sb.append(nl)
            addr -= 128
        return "".join(sb).upper()

    # --- Breakpoint management ---
    def add_breakpoint(self, n):
        if n >= self.linecount:
            raise ProgramMemoryOutOfRangeException(n)
        self.breakpoints.add(n)
        self.prog_mem[n].is_break = True

    def clear_breakpoint(self, n):
        if n >= self.linecount:
            raise ProgramMemoryOutOfRangeException(n)
        self.breakpoints.discard(n)
        self.prog_mem[n].is_break = False

    def clear_breakpoints(self):
        self.breakpoints = set()
        for i in range(self.linecount):
            self.prog_mem[i].is_break = False

    def get_nop_to_add_list(self):
        self.nop_to_add_list.sort(reverse=True)
        return self.nop_to_add_list

    def get_inst_to_replace_list(self):
        self.inst_to_replace_list.sort()
        return self.inst_to_replace_list
