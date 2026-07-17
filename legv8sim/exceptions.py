class DuplicateLabelException(Exception):
    def __init__(self, label):
        self.label = label
        super().__init__(f"LEGISS: label '{label}' is defined more than once")


class IllegalOpcodeException(Exception):
    def __init__(self, opcode, instruction):
        self.opcode = opcode
        self.instruction = instruction
        super().__init__(f"LEGISS: illegal opcode '{opcode}' in instruction\n\t{instruction}")


class IllegalOperandsException(Exception):
    def __init__(self, opA, opB, instruction):
        self.opA = opA
        self.opB = opB
        self.instruction = instruction
        super().__init__(f"LEGISS: illegal operands '{opA}', '{opB}' in instruction\n\t{instruction}")


class IncorrectArgumentCountException(Exception):
    def __init__(self, count, instruction):
        self.count = count
        self.instruction = instruction
        super().__init__(f"LEGISS: incorrect argument count {count} in instruction\n\t{instruction}")


class InvalidConstantException(Exception):
    def __init__(self, constant, instruction):
        self.constant = constant
        self.instruction = instruction
        super().__init__(f"LEGISS: invalid constant '{constant}' in instruction\n\t{instruction}")


class InvalidRegisterException(Exception):
    def __init__(self, reg, instruction):
        self.reg = reg
        self.instruction = instruction
        super().__init__(f"LEGISS: invalid register '{reg}' in instruction\n\t{instruction}")


class MisalignedDataException(Exception):
    def __init__(self, addr, instruction):
        self.addr = addr
        self.instruction = instruction
        super().__init__(f"LEGISS: data memory address 0x{addr:05x} misaligned in\n\t{instruction}")


class NonExistentLabelException(Exception):
    def __init__(self, label):
        self.label = label
        super().__init__(f"LEGISS: label '{label}' not found")


class NonExistentTargetException(Exception):
    def __init__(self, target):
        self.target = target
        super().__init__(f"LEGISS: branch target '{target}' not found")


class OffsetOutOfRangeException(Exception):
    def __init__(self, offset, instruction):
        self.offset = offset
        self.instruction = instruction
        super().__init__(f"LEGISS: offset {offset} out of range in instruction\n\t{instruction}")


class ProgramMemoryOutOfRangeException(Exception):
    def __init__(self, n):
        self.n = n
        super().__init__(f"LEGISS: program memory index {n} out of range")


class ShamtOutOfRangeException(Exception):
    def __init__(self, shamt, instruction):
        self.shamt = shamt
        self.instruction = instruction
        super().__init__(f"LEGISS: shift amount {shamt} out of range in instruction\n\t{instruction}")
