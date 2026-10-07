import argparse
import re
import sys
from collections import deque, defaultdict

IDENTIFIER = r"[\w']+"
INPUT_PATTERN = re.compile(rf"INPUT\s*\(\s*({IDENTIFIER})\s*\)", re.IGNORECASE)
OUTPUT_PATTERN = re.compile(rf"OUTPUT\s*\(\s*({IDENTIFIER})\s*\)", re.IGNORECASE)
GATE_PATTERN = re.compile(rf"({IDENTIFIER})\s*=\s*(\w+)\s*\((.*?)\)", re.IGNORECASE)

SUPPORTED_GATES = {"AND", "BUFF", "NAND", "NOR", "NOT", "OR", "XOR"}
MAX_TRUTH_TABLE_INPUTS = 16


class Circuit:
    """Holds the parsed structure of the combinational circuit using integer IDs."""
    def __init__(self):
        self.node_to_id = {}
        self.id_to_node = []
        self.inputs = []
        self.outputs = []
        self.gates = []
        self.sorted_gates = []

    def get_id(self, name):
        """Map a string node name to a sequential integer ID."""
        if name not in self.node_to_id:
            self.node_to_id[name] = len(self.id_to_node)
            self.id_to_node.append(name)
        return self.node_to_id[name]

    def get_name(self, node_id):
        """Retrieve the original string name of a node."""
        return self.id_to_node[node_id]


def parse_bench(file_path):
    """Parse a BENCH netlist and perform iterative topological sorting."""
    circuit = Circuit()
    inputs_set = set()
    outputs_set = set()
    gate_by_out = {}

    with open(file_path, "r", encoding="utf-8") as bench_file:
        for line_number, raw_line in enumerate(bench_file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            input_match = INPUT_PATTERN.fullmatch(line)
            if input_match:
                node_name = input_match.group(1)
                if node_name in inputs_set:
                    raise ValueError(f"Line {line_number}: duplicate input '{node_name}'")
                inputs_set.add(node_name)
                circuit.inputs.append(circuit.get_id(node_name))
                continue

            output_match = OUTPUT_PATTERN.fullmatch(line)
            if output_match:
                node_name = output_match.group(1)
                if node_name in outputs_set:
                    raise ValueError(f"Line {line_number}: duplicate output '{node_name}'")
                outputs_set.add(node_name)
                circuit.outputs.append(circuit.get_id(node_name))
                continue

            gate_match = GATE_PATTERN.fullmatch(line)
            if gate_match:
                out_name = gate_match.group(1)
                gate_type = gate_match.group(2).upper()
                gate_input_names = [n.strip() for n in gate_match.group(3).split(",") if n.strip()]

                if gate_type not in SUPPORTED_GATES:
                    raise ValueError(f"Line {line_number}: unsupported gate '{gate_type}'")
                if not gate_input_names:
                    raise ValueError(f"Line {line_number}: gate '{out_name}' has no inputs")
                if gate_type in {"NOT", "BUFF"} and len(gate_input_names) != 1:
                    raise ValueError(
                        f"Line {line_number}: {gate_type} gate '{out_name}' "
                        "must have exactly one input"
                    )

                out_id = circuit.get_id(out_name)
                if out_name in inputs_set or out_id in gate_by_out:
                    raise ValueError(f"Node '{out_name}' has multiple definitions")

                in_ids = [circuit.get_id(n) for n in gate_input_names]
                gate = {
                    "out": out_id,
                    "type": gate_type,
                    "inputs": in_ids,
                    "count": len(in_ids),
                }
                circuit.gates.append(gate)
                gate_by_out[out_id] = gate
                continue

            raise ValueError(f"Line {line_number}: could not parse '{line}'")

    defined_nodes = set(circuit.inputs) | set(gate_by_out.keys())
    undefined = [
        circuit.get_name(i) for i in range(len(circuit.id_to_node))
        if i not in defined_nodes
    ]
    if undefined:
        raise ValueError(f"Nodes used but never defined: {', '.join(undefined)}")

    num_nodes = len(circuit.id_to_node)
    in_degree = [0] * num_nodes
    adj_list = [[] for _ in range(num_nodes)]

    for gate in circuit.gates:
        out_id = gate["out"]
        for in_id in gate["inputs"]:
            adj_list[in_id].append(out_id)
            in_degree[out_id] += 1

    levels = [0] * num_nodes
    queue = deque([i for i in range(num_nodes) if in_degree[i] == 0])
    
    visited_count = 0
    while queue:
        curr = queue.popleft()
        visited_count += 1

        if curr in gate_by_out:
            gate = gate_by_out[curr]
            gate["level"] = levels[curr]
            circuit.sorted_gates.append(gate)

        for neighbor in adj_list[curr]:
            in_degree[neighbor] -= 1
            levels[neighbor] = max(levels[neighbor], levels[curr] + 1)
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != num_nodes:
        raise ValueError("Circuit contains a combinational loop (cycle)")

    return circuit


def evaluate_circuit(circuit, input_values, num_bits=1):
    missing = [circuit.get_name(i) for i in circuit.inputs if i not in input_values]
    if missing:
        raise ValueError(f"Missing input values for: {', '.join(missing)}")

    values = [0] * len(circuit.id_to_node)
    for in_id, val in input_values.items():
        values[in_id] = val

    mask = (1 << num_bits) - 1

    for gate in circuit.sorted_gates:
        g_type = gate["type"]
        ins = gate["inputs"]
        
        if g_type == "AND":
            res = values[ins[0]]
            for idx in ins[1:]: res &= values[idx]
        elif g_type == "OR":
            res = values[ins[0]]
            for idx in ins[1:]: res |= values[idx]
        elif g_type == "NAND":
            res = values[ins[0]]
            for idx in ins[1:]: res &= values[idx]
            res = (~res) & mask
        elif g_type == "NOR":
            res = values[ins[0]]
            for idx in ins[1:]: res |= values[idx]
            res = (~res) & mask
        elif g_type == "XOR":
            res = values[ins[0]]
            for idx in ins[1:]: res ^= values[idx]
        elif g_type == "NOT":
            res = (~values[ins[0]]) & mask
        else:  # BUFF
            res = values[ins[0]]
            
        values[gate["out"]] = res

    return {out_id: values[out_id] for out_id in circuit.outputs}


def collapsed_fault_list(circuit):
    fault_lines = []
    total_faults = 0

    for n in circuit.inputs:
        name = circuit.get_name(n)
        fault_lines.append(f"INPUT({name}): sa0, sa1")
        total_faults += 2

    input_faults = {"AND": 1, "NAND": 1, "OR": 0, "NOR": 0}
    output_faults = {"AND": 0, "NAND": 1, "OR": 1, "NOR": 0}

    for gate in circuit.sorted_gates:
        g_type = gate["type"]
        out_name = circuit.get_name(gate["out"])
        gate_faults = []

        if g_type in input_faults:
            for i, in_id in enumerate(gate["inputs"], start=1):
                in_name = circuit.get_name(in_id)
                gate_faults.append(f"input {i}({in_name}) - sa{input_faults[g_type]}")
                total_faults += 1
            gate_faults.append(f"output - sa{output_faults[g_type]}")
            total_faults += 1
            
        elif g_type in {"NOT", "BUFF"}:
            gate_faults.extend(["output - sa0", "output - sa1"])
            total_faults += 2
            
        else:  # XOR faults are retained at every pin
            for i, in_id in enumerate(gate["inputs"], start=1):
                in_name = circuit.get_name(in_id)
                gate_faults.extend([f"input {i}({in_name}) - sa0", f"input {i}({in_name}) - sa1"])
                total_faults += 2
            gate_faults.extend(["output - sa0", "output - sa1"])
            total_faults += 2

        fault_lines.append(f"{out_name}: {', '.join(gate_faults)}")

    for n in circuit.outputs:
        name = circuit.get_name(n)
        fault_lines.append(f"OUTPUT({name}): sa0, sa1")
        total_faults += 2

    return total_faults, fault_lines


def print_summary(circuit):
    input_names = [circuit.get_name(i) for i in circuit.inputs]
    output_names = [circuit.get_name(i) for i in circuit.outputs]
    print("--- Circuit Benchmark Summary ---")
    print(f"Inputs  ({len(input_names)}): {', '.join(input_names)}")
    print(f"Outputs ({len(output_names)}): {', '.join(output_names)}")
    
    print("\nNodes by Level:")
    outputs_set = set(circuit.outputs)
    
    print("Level 0:")
    for node_id in circuit.inputs:
        output_label = " (OUTPUT)" if node_id in outputs_set else ""
        print(f"  {circuit.get_name(node_id)}: INPUT{output_label}")
        
    level_groups = defaultdict(list)
    for gate in circuit.sorted_gates:
        lvl = gate["level"]
        out_lbl = " (OUTPUT)" if gate["out"] in outputs_set else ""
        gate_inputs = ", ".join(circuit.get_name(i) for i in gate["inputs"])
        node_str = f"{circuit.get_name(gate['out'])}: {gate['count']}-input {gate['type']} of {gate_inputs}{out_lbl}"
        level_groups[lvl].append(node_str)
        
    for lvl in sorted(level_groups.keys()):
        print(f"\nLevel {lvl}:")
        for node_str in level_groups[lvl]:
            print(f"  {node_str}")


def print_truth_table(circuit):
    num_inputs = len(circuit.inputs)
    total_rows = 1 << num_inputs
    input_values = {}

    for i, in_id in enumerate(circuit.inputs):
        chunk_size = 1 << (num_inputs - 1 - i)
        pattern = ((1 << chunk_size) - 1) << chunk_size
        repeats = total_rows // (2 * chunk_size)
        col_val = 0
        for _ in range(repeats):
            col_val = (col_val << (2 * chunk_size)) | pattern
        input_values[in_id] = col_val

    output_values = evaluate_circuit(circuit, input_values, num_bits=total_rows)
    merged_values = {**input_values, **output_values}
    headings = [circuit.get_name(i) for i in circuit.inputs + circuit.outputs]
    
    print("\nTruth table:")
    print(" ".join(headings))
    
    for row in range(total_rows):
        row_strs = []
        for node_id in circuit.inputs + circuit.outputs:
            bit = (merged_values[node_id] >> row) & 1
            row_strs.append(str(bit))
        print(" ".join(row_strs))


def parse_input_assignments(assignments, circuit):
    values = {}
    input_names = {circuit.get_name(i) for i in circuit.inputs}
    
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Invalid input '{assignment}'; expected NAME=0 or NAME=1")
        node_name, value = assignment.split("=", 1)
        if node_name not in input_names:
            raise ValueError(f"Unknown input '{node_name}'")
            
        node_id = circuit.get_id(node_name)
        if node_id in values:
            raise ValueError(f"Input '{node_name}' was assigned more than once")
        if value not in {"0", "1"}:
            raise ValueError(f"Input '{node_name}' must be assigned 0 or 1")
        values[node_id] = int(value)
    return values


def prompt_for_input_values(circuit):
    if not circuit.inputs:
        return {}
    input_names = [circuit.get_name(i) for i in circuit.inputs]
    input_order = ", ".join(input_names)
    
    while True:
        try:
            bit_string = input(f"\nEnter one bit per input in this order ({input_order}): ").strip()
        except EOFError as error:
            raise ValueError("No test vector was entered.") from error
            
        if len(bit_string) == len(circuit.inputs) and all(bit in {"0", "1"} for bit in bit_string):
            return {
                circuit.get_id(name): int(bit)
                for name, bit in zip(input_names, bit_string)
            }
        print(f"Enter exactly {len(circuit.inputs)} bits using only 0 and 1.")


def ask_yes_no(prompt):
    """Interactively ask a yes/no question and return a boolean."""
    while True:
        try:
            response = input(prompt).strip().lower()
            if response in {"y", "yes"}:
                return True
            if response in {"n", "no"}:
                return False
            print("Please answer 'y' or 'n'.")
        except EOFError:
            print()
            return False


def main():
    argument_parser = argparse.ArgumentParser(description="Parse and evaluate a combinational BENCH circuit.")
    argument_parser.add_argument("circuit_file", help="path to a .bench file")
    argument_parser.add_argument(
        "--input", action="append", default=[], metavar="NAME=BIT",
        help="input assignment (repeat once per input to evaluate the circuit)",
    )
    arguments = argument_parser.parse_args()

    try:
        circuit = parse_bench(arguments.circuit_file)
        print_summary(circuit)
        
        # Interactive Fault List Prompt
        if ask_yes_no("\nDo you want to print the collapsed fault list? (y/n): "):
            total_faults, fault_lines = collapsed_fault_list(circuit)
            print(f"\nCollapsed stuck-at fault list ({total_faults} total faults):")
            for line in fault_lines:
                print(f"- {line}")

        printed_truth_table = False
        
        # Interactive Truth Table Prompt
        if ask_yes_no("\nDo you want to print the truth table? (y/n): "):
            if len(circuit.inputs) > MAX_TRUTH_TABLE_INPUTS:
                print(f"\n[!] WARNING: Circuit has {len(circuit.inputs)} inputs. "
                      f"A truth table would require 2^{len(circuit.inputs)} rows.")
                print(f"[!] To prevent freezing, the limit is set to {MAX_TRUTH_TABLE_INPUTS} inputs. "
                      "Skipping truth table generation.")
            else:
                print_truth_table(circuit)
                printed_truth_table = True

        # If truth table was skipped or declined, evaluate a single test vector
        if not printed_truth_table:
            input_values = (
                parse_input_assignments(arguments.input, circuit)
                if arguments.input else prompt_for_input_values(circuit)
            )
            output_values = evaluate_circuit(circuit, input_values, num_bits=1)
            print("\nOutput values:")
            for out_id in circuit.outputs:
                print(f"{circuit.get_name(out_id)} = {output_values[out_id]}")
                
    except (OSError, ValueError, KeyboardInterrupt) as error:
        print(f"\nError: {error}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())