# LEGv8 Simulator - Python Edition

Python port of the LEGv8 CPU simulator. Supports single-cycle and 5-stage pipelined execution with hazard detection and forwarding.

Copyright (c) Kenneth Yun, University of California, San Diego. All rights reserved.

Python port by cjyaddone.

## Requirements

- Python 3.9+

No external dependencies; this package uses only the standard library.

## Command-line usage

Run from the directory that contains the `legv8sim` package:

```bash
python -m legv8sim --program <assembly.s> [options]
```

### Options

| Flag | Description |
|------|-------------|
| `--program <file>` | Assembly program file to load (required) |
| `--data <file>` | Data file to load |
| `--run` | Execute the program to completion |
| `--pipelined` | Use pipelined execution mode |
| `--single-cycle` | Use single-cycle execution mode (default) |
| `--dump-registers` | Print register file after execution |
| `--dump-data` | Print data memory after execution |
| `--dump-stack` | Print stack memory after execution |
| `--dump-program` | Print program memory listing |
| `--help`, `-h` | Show help message |

### Examples

Matrix multiplication with pipelining:

```bash
python -m legv8sim \
  --program legv8sim/exampleData/MatrixMul.s \
  --data legv8sim/exampleData/testData_4by4_base2.txt \
  --run --pipelined \
  --dump-registers --dump-data --dump-stack
```

Single-cycle execution:

```bash
python -m legv8sim \
  --program legv8sim/exampleData/MatrixMul.s \
  --data legv8sim/exampleData/testData_4by4_base2.txt \
  --run --single-cycle \
  --dump-registers
```

## Python API usage

You can also embed the simulator directly in Python code:

```python
from legv8sim.simulator import Simulator

sim = Simulator()

# Loading methods return the same log text printed by the CLI.
sim.load_prog("legv8sim/exampleData/MatrixMul.s")
sim.load_data("legv8sim/exampleData/testData_4by4_base2.txt")

# False = single-cycle, True = pipelined.
sim.run(pipelined=True)

print(sim.get_output())
print(sim.dump_reg_file())

# Direct inspection helpers are available for tests and tools.
x0 = sim.get_reg(0)
first_data_word = sim.get_data_mem_word(0)
```

For interactive tools, call `step(pipelined=False)` or `step(pipelined=True)` to advance one cycle/instruction at a time, and use `reset_pc()` or `reset_output()` when re-running loaded state.

## Package structure

```text
legv8sim/
  __init__.py          Package marker
  __main__.py          python -m legv8sim entry
  cli.py               CLI argument parsing
  simulator.py         CPU engine (registers, memory, pipeline, execution)
  instruction.py       Instruction decode and field parsing
  pipeline.py          Pipeline FIFO and shift registers
  exceptions.py        Custom exception classes
  directives.py        Assembly directive enum
  enums.py             NumberType, OpToSetFlags, Precision enums
  models.py            BranchTarget and DataLabel dataclasses
  exampleData/         Sample assembly and data files
  tests/               Regression tests
```

## Supported instructions

About 60 LEGv8 instructions including arithmetic, logical, branches, loads/stores, floating-point, and pseudo-instructions such as `CMP`, `CMPI`, and `MOV`.

See `exampleData/MatrixMul.s` and `tests/data/all_instructions.s` for example programs.
