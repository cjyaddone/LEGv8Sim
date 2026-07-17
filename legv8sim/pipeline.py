class ShiftRegister:
    def __init__(self, size):
        self._max_size = size
        self._data = []

    def insert(self, data):
        self._data.insert(0, data)
        if len(self._data) > self._max_size:
            return self._data.pop()

    def get_at(self, index):
        if index < len(self._data):
            return self._data[index]
        return None

    def clear(self):
        self._data.clear()


class InstructionFIFO:
    MAXFIFOSIZE = 4

    def __init__(self):
        self._fifo = []

    def insert(self, rti):
        self._fifo.insert(0, rti)
        if len(self._fifo) > self.MAXFIFOSIZE:
            return self._fifo.pop()
        return None

    def clear(self):
        self._fifo.clear()

    def size(self):
        return len(self._fifo)

    # Position 0 = IF/ID, 1 = ID/EX, 2 = EX/DM, 3 = DM/WB

    def set_ifid(self, rti):
        if self._fifo:
            self._fifo[0] = rti

    def set_idex(self, rti):
        if len(self._fifo) >= 2:
            self._fifo[1] = rti

    def set_exdm(self, rti):
        if len(self._fifo) >= 3:
            self._fifo[2] = rti

    def set_dmwb(self, rti):
        if len(self._fifo) == 4:
            self._fifo[3] = rti

    def ifid(self):
        return self._fifo[0] if self._fifo else None

    def idex(self):
        return self._fifo[1] if len(self._fifo) > 1 else None

    def exdm(self):
        return self._fifo[2] if len(self._fifo) > 2 else None

    def dmwb(self):
        return self._fifo[3] if len(self._fifo) > 3 else None

    def raw_rf_data_hazard_at(self, n):
        reg = 31
        if len(self._fifo) >= 3:
            rc = self._fifo[2].rC if self._is_rd_output(self._fifo[2]) else 31
            ra = self._fifo[1].rA
            rb = self._fifo[1].rB
            rt = self._fifo[1].rC if self._is_rt_input(self._fifo[1]) else 31
            if (n == 1 and rc == ra) or (n == 2 and rc == rb) or (n == 3 and rc == rt):
                reg = rc
        return reg

    def raw_dm_data_hazard_at(self, n):
        reg = 31
        if len(self._fifo) == 4:
            rc = self._fifo[3].rC if self._is_rd_output(self._fifo[3]) else 31
            ra = self._fifo[1].rA
            rb = self._fifo[1].rB
            rt = self._fifo[1].rC if self._is_rt_input(self._fifo[1]) else 31
            if (n == 1 and rc == ra) or (n == 2 and rc == rb) or (n == 3 and rc == rt):
                reg = rc
        return reg

    def wb_reg_branch_hazard_at(self):
        reg = 31
        if len(self._fifo) == 4:
            rc = self._fifo[3].rC if self._is_rd_output(self._fifo[3]) else 31
            branch_reg = self._fifo[0].rC if self._is_reg_branch(self._fifo[0]) else 31
            if rc == branch_reg:
                reg = rc
        return reg

    def dm_reg_branch_hazard_at(self):
        reg = 31
        if len(self._fifo) >= 3:
            rc = self._fifo[2].rC if self._is_rd_output(self._fifo[2]) else 31
            branch_reg = self._fifo[0].rC if self._is_reg_branch(self._fifo[0]) else 31
            if rc == branch_reg:
                reg = rc
        return reg

    def ex_reg_branch_hazard_at(self):
        reg = 31
        if len(self._fifo) >= 2:
            rc = self._fifo[1].rC if self._is_rd_output(self._fifo[1]) else 31
            branch_reg = self._fifo[0].rC if self._is_reg_branch(self._fifo[0]) else 31
            if rc == branch_reg:
                reg = rc
        return reg

    def need_to_stall(self):
        if len(self._fifo) >= 2 and self._is_load(self._fifo[1]):
            if (self._fifo[1].rC == self._fifo[0].rA
                    or self._fifo[1].rC == self._fifo[0].rB
                    or (self._is_rt_input(self._fifo[0]) and self._fifo[1].rC == self._fifo[0].rC)
                    or (self._is_reg_branch(self._fifo[0]) and self._fifo[1].rC == self._fifo[0].rC)):
                return True
        if self._fifo and self._fifo[0].op == 0:
            return True
        return False

    @staticmethod
    def _is_load(rti):
        # STXR's status result is produced by the memory stage as well.
        return rti.op in (1986, 2018, 1506, 1476, 962, 450, 1602, 1600)

    @staticmethod
    def _is_reg_branch(rti):
        return rti.op in (1712, 180, 181)

    @staticmethod
    def _is_rt_input(rti):
        return rti.op in (485, 1984, 2016, 1472, 1504, 960, 448, 2, 3)

    @staticmethod
    def _is_rd_output(rti):
        return rti.op not in (180, 181, 1984, 2016, 1472, 1504, 960, 448, 1712, 2, 3)
