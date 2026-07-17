import argparse
import sys

from legv8sim.simulator import Simulator


def main():
    parser = argparse.ArgumentParser(
        prog="legv8sim",
        description="LEGv8 Instruction Set Simulator - CLI Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python -m legv8sim --program samples/test.asm --run --dump-registers
  python -m legv8sim --program samples/finalCode.s --data samples/testData_4by4_base2.txt --run --pipelined"""
    )
    parser.add_argument("--program", required=True, metavar="FILE",
                        help="Assembly program file to load")
    parser.add_argument("--data", metavar="FILE",
                        help="Data file to load (optional)")
    parser.add_argument("--run", action="store_true",
                        help="Execute the program to completion")
    parser.add_argument("--pipelined", action="store_true", default=False,
                        help="Use pipelined execution mode")
    parser.add_argument("--single-cycle", action="store_true", default=False,
                        help="Use single-cycle execution mode (default)")
    parser.add_argument("--dump-registers", action="store_true",
                        help="Print register file after execution")
    parser.add_argument("--dump-data", action="store_true",
                        help="Print data memory after execution")
    parser.add_argument("--dump-stack", action="store_true",
                        help="Print stack memory after execution")
    parser.add_argument("--dump-program", action="store_true",
                        help="Print program memory listing")

    args = parser.parse_args()

    pipelined = args.pipelined and not args.single_cycle
    simulator = Simulator()

    try:
        # Load program
        prog_log = simulator.load_prog(args.program)
        print(prog_log, end="")

        # Load data if specified
        if args.data:
            data_log = simulator.load_data(args.data)
            print(data_log, end="")

        if args.run:
            simulator.run(pipelined)

            # Print program I/O output
            output = simulator.get_output()
            if output:
                print(output)

            # Dump requested state
            if args.dump_program:
                print("\n===== Program Memory =====")
                print(_dump_program_memory(simulator))
            if args.dump_registers:
                print("===== Register File =====")
                print(simulator.dump_reg_file())
            if args.dump_data:
                print("===== Data Memory =====")
                print(simulator.dump_data_mem(0))
            if args.dump_stack:
                print("===== Stack =====")
                print(simulator.dump_stack(262136))
        else:
            print("\nProgram loaded successfully. Use --run to execute.")
            if args.dump_program:
                print("\n===== Program Memory =====")
                print(_dump_program_memory(simulator))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _dump_program_memory(simulator):
    sb = []
    for i in range(simulator.linecount):
        sb.append(str(simulator.prog_mem[i]))
        sb.append("\n")
    return "".join(sb)


if __name__ == "__main__":
    main()
