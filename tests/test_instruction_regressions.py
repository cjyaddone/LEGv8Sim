import contextlib
import io
import os
import struct
import tempfile
import unittest

from legv8sim.exceptions import OffsetOutOfRangeException
from legv8sim.instruction import Instruction
from legv8sim.simulator import MASK64, Simulator


def make_instruction(*fields, line_number=0):
    instruction = Instruction(line_number)
    instruction.set_fields(list(fields))
    return instruction


def run_program(instructions, pipelined=False, registers=None):
    simulator = Simulator()
    for line_number, fields in enumerate(instructions):
        simulator.prog_mem[line_number] = make_instruction(
            *fields, line_number=line_number
        )
    simulator.linecount = len(instructions)
    simulator.prog_mem[0].stage = "IF"
    for register, value in (registers or {}).items():
        simulator.reg_file[register] = value & MASK64
    with contextlib.redirect_stdout(io.StringIO()):
        simulator.run(pipelined)
    return simulator


class IntegerInstructionTests(unittest.TestCase):
    def test_suboperation_selectors_match_java_instruction_decoder(self):
        cases = (
            (("MUL", "X0", "X1", "X2"), 31),
            (("SDIV", "X0", "X1", "X2"), 2),
            (("UDIV", "X0", "X1", "X2"), 3),
            (("FADDS", "S0", "S1", "S2"), 10),
            (("FCMPD", "D1", "D2"), 8),
        )
        for fields, expected_opx in cases:
            instruction = make_instruction(*fields)
            self.assertEqual(instruction.opx, expected_opx)
            self.assertEqual(instruction.cond, 0)

    def test_udiv_by_two_matches_lsr(self):
        for pipelined in (False, True):
            for value in (0, 1, 2, 3, 10, 1 << 63, MASK64):
                simulator = run_program(
                    [
                        ("UDIV", "X3", "X1", "X2"),
                        ("LSR", "X4", "X1", "#1"),
                        ("STOP",),
                    ],
                    pipelined=pipelined,
                    registers={1: value, 2: 2},
                )
                self.assertEqual(simulator.get_reg(3), value >> 1)
                self.assertEqual(simulator.get_reg(3), simulator.get_reg(4))

    def test_sdiv_truncates_toward_zero_and_handles_edge_cases(self):
        simulator = Simulator()
        instruction = make_instruction("SDIV", "X3", "X1", "X2")
        cases = (
            (-5, 2, -2),
            (5, -2, -2),
            (-5, -2, 2),
            (5, 0, 0),
            (-(1 << 63), -1, -(1 << 63)),
        )
        for dividend, divisor, expected in cases:
            actual = simulator._execute(instruction, dividend, divisor, 0)
            self.assertEqual(actual, expected & MASK64)

    def test_movk_replaces_selected_halfword(self):
        simulator = Simulator()
        instruction = make_instruction("MOVK", "X0", "#0", "LSL", "#16")
        self.assertEqual(
            simulator._execute(instruction, 0, 0, MASK64),
            0xFFFFFFFF0000FFFF,
        )

    def test_umulh_treats_high_bit_operands_as_unsigned(self):
        simulator = Simulator()
        instruction = make_instruction("UMULH", "X0", "X1", "X2")
        expected = ((MASK64 * MASK64) >> 64) & MASK64
        self.assertEqual(simulator._execute(instruction, MASK64, MASK64, 0), expected)

    def test_java_compatible_putchar_and_putint(self):
        simulator = Simulator()
        simulator._write_rf(make_instruction("PUTCHAR", "X0"), 0x263A)
        simulator._write_rf(make_instruction("PUTINT", "X0"), MASK64)
        self.assertEqual(simulator.get_output(), "☺-1")


class FloatingPointInstructionTests(unittest.TestCase):
    def test_float_suboperation_selector_is_executed(self):
        simulator = Simulator()
        single = make_instruction("FADDS", "S0", "S1", "S2")
        double = make_instruction("FMULD", "D0", "D1", "D2")
        f1 = struct.unpack(">I", struct.pack(">f", 1.5))[0]
        f2 = struct.unpack(">I", struct.pack(">f", 2.25))[0]
        d1 = struct.unpack(">Q", struct.pack(">d", 1.5))[0]
        d2 = struct.unpack(">Q", struct.pack(">d", 2.0))[0]
        with contextlib.redirect_stdout(io.StringIO()):
            single_result = simulator._execute(single, f1, f2, 0)
            double_result = simulator._execute(double, d1, d2, 0)
        self.assertEqual(struct.unpack(">f", struct.pack(">I", single_result))[0], 3.75)
        self.assertEqual(struct.unpack(">d", struct.pack(">Q", double_result))[0], 3.0)

    def test_float_compare_sets_flags(self):
        simulator = Simulator()
        instruction = make_instruction("FCMPS", "S1", "S2")
        one = struct.unpack(">I", struct.pack(">f", 1.0))[0]
        two = struct.unpack(">I", struct.pack(">f", 2.0))[0]
        simulator._execute(instruction, one, two, 0)
        self.assertTrue(simulator.flag_n)
        self.assertFalse(simulator.flag_z)
        self.assertFalse(simulator.flag_c)

    def test_float_divide_by_zero_uses_ieee_results(self):
        simulator = Simulator()
        single = make_instruction("FDIVS", "S0", "S1", "S2")
        double = make_instruction("FDIVD", "D0", "D1", "D2")
        one32 = struct.unpack(">I", struct.pack(">f", 1.0))[0]
        zero32 = struct.unpack(">I", struct.pack(">f", 0.0))[0]
        one64 = struct.unpack(">Q", struct.pack(">d", 1.0))[0]
        neg_zero64 = struct.unpack(">Q", struct.pack(">d", -0.0))[0]
        with contextlib.redirect_stdout(io.StringIO()):
            positive_infinity = simulator._execute(single, one32, zero32, 0)
            negative_infinity = simulator._execute(double, one64, neg_zero64, 0)
            not_a_number = simulator._execute(single, zero32, zero32, 0)
        self.assertEqual(positive_infinity, 0x7F800000)
        self.assertEqual(negative_infinity, 0xFFF0000000000000)
        self.assertTrue(
            struct.unpack(">f", struct.pack(">I", not_a_number))[0] !=
            struct.unpack(">f", struct.pack(">I", not_a_number))[0]
        )

    def test_single_precision_overflow_becomes_infinity(self):
        simulator = Simulator()
        instruction = make_instruction("FMULS", "S0", "S1", "S2")
        largest = 0x7F7FFFFF
        two = struct.unpack(">I", struct.pack(">f", 2.0))[0]
        with contextlib.redirect_stdout(io.StringIO()):
            result = simulator._execute(instruction, largest, two, 0)
        self.assertEqual(result, 0x7F800000)

    def test_nan_results_use_java_canonical_bit_patterns(self):
        simulator = Simulator()
        single = make_instruction("FADDS", "S0", "S1", "S2")
        double = make_instruction("FADDD", "D0", "D1", "D2")
        with contextlib.redirect_stdout(io.StringIO()):
            single_result = simulator._execute(single, 0x7F800001, 0, 0)
            double_result = simulator._execute(double, 0x7FF0000000000001, 0, 0)
        self.assertEqual(single_result, 0x7FC00000)
        self.assertEqual(double_result, 0x7FF8000000000000)


class MemoryInstructionTests(unittest.TestCase):
    def test_d_format_accepts_negative_256_offset(self):
        instruction = make_instruction("LDUR", "X0", "X1", "#-256")
        self.assertEqual(instruction.offset, -256)
        with self.assertRaises(OffsetOutOfRangeException):
            make_instruction("LDUR", "X0", "X1", "#-257")

    def test_stxr_uses_status_value_and_address_registers(self):
        for pipelined in (False, True):
            simulator = run_program(
                [
                    ("LDXR", "X6", "X2", "#0"),
                    ("STXR", "X3", "X1", "X2"),
                    ("ADDI", "X5", "X3", "#1"),
                    ("LDUR", "X4", "X2", "#0"),
                    ("STOP",),
                ],
                pipelined=pipelined,
                registers={1: 0x123456789ABCDEF0, 2: 64, 3: MASK64},
            )
            self.assertEqual(simulator.get_data_mem_word(8), 0x123456789ABCDEF0)
            self.assertEqual(simulator.get_reg(3), 0)
            self.assertEqual(simulator.get_reg(4), 0x123456789ABCDEF0)
            self.assertEqual(simulator.get_reg(5), 1)

    def test_stxr_fails_without_matching_ldxr(self):
        for pipelined in (False, True):
            simulator = run_program(
                [
                    ("STXR", "X3", "X1", "X2"),
                    ("STOP",),
                ],
                pipelined=pipelined,
                registers={1: 0x1234, 2: 64},
            )
            self.assertEqual(simulator.get_data_mem_word(8), 0)
            self.assertEqual(simulator.get_reg(3), 1)


class ParserRegressionTests(unittest.TestCase):
    def test_standalone_label_can_target_stop(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".s", delete=False) as source:
            source.write("B done\ndone:\nSTOP\n")
            source_path = source.name
        try:
            simulator = Simulator()
            simulator.load_prog(source_path)
            self.assertEqual(simulator._get_inst_addr("DONE"), 1)
            self.assertEqual(simulator.prog_mem[1].opcode, "STOP")
        finally:
            os.unlink(source_path)


if __name__ == "__main__":
    unittest.main()
