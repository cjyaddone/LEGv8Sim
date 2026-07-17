from dataclasses import dataclass


@dataclass
class BranchTarget:
    label: str
    inst_addr: int


@dataclass
class DataLabel:
    label: str
    data_addr: int
