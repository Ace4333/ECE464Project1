import argparse
from itertools import product
import re
import sys


IDENTIFIER = r"[\w']+"
INPUT_PATTERN = re.compile(rf"INPUT\s*\(\s*({IDENTIFIER})\s*\)", re.IGNORECASE)
OUTPUT_PATTERN = re.compile(rf"OUTPUT\s*\(\s*({IDENTIFIER})\s*\)", re.IGNORECASE)
GATE_PATTERN = re.compile(
    rf"({IDENTIFIER})\s*=\s*(\w+)\s*\((.*?)\)", re.IGNORECASE
)
SUPPORTED_GATES = {"AND", "BUFF", "NAND", "NOR", "NOT", "OR", "XOR"}
MAX_TRUTH_TABLE_INPUTS = 16


def parse_bench(file_path):
    """Parse a BENCH netlist and return its inputs, outputs, and ordered gates."""
    inputs = []
    outputs = []
    gates = []

    with open(file_path, "r", encoding="utf-8") as bench_file:
        for line_number, raw_line in enumerate(bench_file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            input_match = INPUT_PATTERN.fullmatch(line)
            if input_match:
                node = input_match.group(1)
                if node in inputs:
                    raise ValueError(f"Line {line_number}: duplicate input '{node}'")
                inputs.append(node)
                continue

            output_match = OUTPUT_PATTERN.fullmatch(line)
            if output_match:
                node = output_match.group(1)
                if node in outputs:
                    raise ValueError(f"Line {line_number}: duplicate output '{node}'")
                outputs.append(node)
                continue

            gate_match = GATE_PATTERN.fullmatch(line)
            if gate_match:
                out_node = gate_match.group(1)
                gate_type = gate_match.group(2).upper()
                gate_inputs = [
                    node.strip()
                    for node in gate_match.group(3).split(",")
                    if node.strip()
                ]
                if gate_type not in SUPPORTED_GATES:
                    raise ValueError(
                        f"Line {line_number}: unsupported gate type '{gate_type}'"
                    )
                if not gate_inputs:
                    raise ValueError(
                        f"Line {line_number}: gate '{out_node}' has no inputs"
                    )
                if gate_type in {"NOT", "BUFF"} and len(gate_inputs) != 1:
                    raise ValueError(
                        f"Line {line_number}: {gate_type} gate '{out_node}' "
                        "must have exactly one input"
                    )
                gates.append(
                    {
                        "out": out_node,
                        "type": gate_type,
                        "inputs": gate_inputs,
                        "count": len(gate_inputs),
                    }
                )
                continue

            raise ValueError(f"Line {line_number}: could not parse '{line}'")

    gate_by_output = {}
    for gate in gates:
        node = gate["out"]
        if node in inputs or node in gate_by_output:
            raise ValueError(f"Node '{node}' has multiple definitions")
        gate_by_output[node] = gate

    node_levels = {node: 0 for node in inputs}

    def get_level(node, visiting):
        if node in node_levels:
            return node_levels[node]
        if node not in gate_by_output:
            raise ValueError(f"Node '{node}' is used but never defined")
        if node in visiting:
            raise ValueError(f"Cycle detected while finding level for '{node}'")

        visiting.add(node)
        gate = gate_by_output[node]
        input_levels = [get_level(input_node, visiting) for input_node in gate["inputs"]]
        visiting.remove(node)
        node_levels[node] = 1 + max(input_levels)
        return node_levels[node]

    for gate in gates:
        gate["level"] = get_level(gate["out"], set())
    for output in outputs:
        get_level(output, set())

    gates.sort(key=lambda gate: gate["level"])
    return {"inputs": inputs, "outputs": outputs, "gates": gates}


def evaluate_circuit(circuit, input_values):
    """Evaluate a parsed circuit for one complete assignment of input bits."""
    inputs = circuit["inputs"]
    missing = [node for node in inputs if node not in input_values]
    extra = [node for node in input_values if node not in inputs]
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing input values for: {', '.join(missing)}")
        if extra:
            details.append(f"unknown inputs: {', '.join(extra)}")
        raise ValueError("; ".join(details))

    values = {}
    for node in inputs:
        value = input_values[node]
        if not isinstance(value, (bool, int)) or value not in (0, 1):
            raise ValueError(f"Input '{node}' must be 0 or 1, not {value!r}")
        values[node] = bool(value)

    for gate in circuit["gates"]:
        gate_inputs = [values[node] for node in gate["inputs"]]
        gate_type = gate["type"]
        if gate_type == "AND":
            result = all(gate_inputs)
        elif gate_type == "NAND":
            result = not all(gate_inputs)
        elif gate_type == "OR":
            result = any(gate_inputs)
        elif gate_type == "NOR":
            result = not any(gate_inputs)
        elif gate_type == "XOR":
            result = sum(gate_inputs) % 2 == 1
        elif gate_type == "NOT":
            result = not gate_inputs[0]
        else:  # BUFF
            result = gate_inputs[0]
        values[gate["out"]] = result

    return {node: int(values[node]) for node in circuit["outputs"]}


def collapsed_fault_list(circuit):
    """Return collapsed gate-pin faults plus primary input and output faults."""
    faults = [
        f"INPUT({node}) stuck-at-{stuck_value}"
        for node in circuit["inputs"]
        for stuck_value in (0, 1)
    ]
    input_faults = {
        "AND": 1,
        "NAND": 1,
        "OR": 0,
        "NOR": 0,
    }
    output_faults = {
        "AND": 0,
        "NAND": 1,
        "OR": 1,
        "NOR": 0,
    }

    for gate in circuit["gates"]:
        gate_type = gate["type"]
        if gate_type in input_faults:
            for index, node in enumerate(gate["inputs"], start=1):
                faults.append(
                    f"{gate['out']} input {index} ({node}) stuck-at-{input_faults[gate_type]}"
                )
            faults.append(
                f"{gate['out']} output stuck-at-{output_faults[gate_type]}"
            )
        elif gate_type in {"NOT", "BUFF"}:
            faults.extend(
                (
                    f"{gate['out']} output stuck-at-0",
                    f"{gate['out']} output stuck-at-1",
                )
            )
        else:  # XOR faults are retained at every input and output pin.
            for index, node in enumerate(gate["inputs"], start=1):
                for stuck_value in (0, 1):
                    faults.append(
                        f"{gate['out']} input {index} ({node}) "
                        f"stuck-at-{stuck_value}"
                    )
            for stuck_value in (0, 1):
                faults.append(
                    f"{gate['out']} output stuck-at-{stuck_value}"
                )
    faults.extend(
        f"OUTPUT({node}) stuck-at-{stuck_value}"
        for node in circuit["outputs"]
        for stuck_value in (0, 1)
    )
    return faults


def print_summary(circuit):
    inputs = circuit["inputs"]
    outputs = circuit["outputs"]
    gates = circuit["gates"]
    print("--- Circuit Benchmark Summary ---")
    print(f"Inputs  ({len(inputs)}): {', '.join(inputs)}")
    print(f"Outputs ({len(outputs)}): {', '.join(outputs)}")
    print("\nNodes (level order):")
    for node in inputs:
        output_label = " OUTPUT" if node in outputs else ""
        print(f"{node} (level 0): INPUT{output_label}")
    for gate in gates:
        gate_inputs = ", ".join(gate["inputs"])
        output_label = " OUTPUT" if gate["out"] in outputs else ""
        print(
            f"{gate['out']} (level {gate['level']}): "
            f"{gate['count']}-input {gate['type']} of {gate_inputs}{output_label}"
        )


def print_fault_list(circuit):
    faults = collapsed_fault_list(circuit)
    print(f"\nCollapsed stuck-at fault list ({len(faults)} faults):")
    for fault in faults:
        print(f"- {fault}")


def parse_input_assignments(assignments, input_nodes):
    values = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(
                f"Invalid input assignment '{assignment}'; expected NAME=0 or NAME=1"
            )
        node, value = assignment.split("=", 1)
        if node not in input_nodes:
            raise ValueError(f"Unknown input '{node}'")
        if node in values:
            raise ValueError(f"Input '{node}' was assigned more than once")
        if value not in {"0", "1"}:
            raise ValueError(f"Input '{node}' must be assigned 0 or 1")
        values[node] = int(value)
    return values


def prompt_for_input_values(input_nodes):
    if not input_nodes:
        return {}
    input_order = ", ".join(input_nodes)
    while True:
        try:
            bit_string = input(
                f"\nEnter one bit per input in this order ({input_order}): "
            ).strip()
        except EOFError as error:
            raise ValueError("No test vector was entered") from error
        if len(bit_string) == len(input_nodes) and all(
            bit in {"0", "1"} for bit in bit_string
        ):
            return {
                node: int(bit)
                for node, bit in zip(input_nodes, bit_string)
            }
        print(f"Enter exactly {len(input_nodes)} bits using only 0 and 1.")


def print_truth_table(circuit):
    if len(circuit["inputs"]) > MAX_TRUTH_TABLE_INPUTS:
        raise ValueError(
            f"Truth table would require 2^{len(circuit['inputs'])} rows; "
            f"the limit is {MAX_TRUTH_TABLE_INPUTS} inputs. Use --input instead."
        )

    headings = circuit["inputs"] + circuit["outputs"]
    print("\nTruth table:")
    print(" ".join(headings))
    for bits in product((0, 1), repeat=len(circuit["inputs"])):
        assignment = dict(zip(circuit["inputs"], bits))
        output_values = evaluate_circuit(circuit, assignment)
        row = bits + tuple(output_values[node] for node in circuit["outputs"])
        print(" ".join(str(bit) for bit in row))


def main():
    argument_parser = argparse.ArgumentParser(
        description="Parse and evaluate a combinational BENCH circuit."
    )
    argument_parser.add_argument("circuit_file", help="path to a .bench file")
    evaluation = argument_parser.add_mutually_exclusive_group()
    evaluation.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="NAME=BIT",
        help="input assignment (repeat once per input to evaluate the circuit)",
    )
    evaluation.add_argument(
        "--truth-table",
        action="store_true",
        help="evaluate every possible input combination (up to 16 inputs)",
    )
    argument_parser.add_argument(
        "--fault-list",
        action="store_true",
        help="print the gate-pin stuck-at fault list after basic fault collapsing",
    )
    arguments = argument_parser.parse_args()

    try:
        circuit = parse_bench(arguments.circuit_file)
        print_summary(circuit)
        if arguments.fault_list:
            print_fault_list(circuit)
        if arguments.truth_table:
            print_truth_table(circuit)
        else:
            input_values = (
                parse_input_assignments(arguments.input, circuit["inputs"])
                if arguments.input
                else prompt_for_input_values(circuit["inputs"])
            )
            output_values = evaluate_circuit(circuit, input_values)
            print("\nOutput values:")
            for node, value in output_values.items():
                print(f"{node} = {value}")
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
