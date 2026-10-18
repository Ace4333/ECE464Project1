import argparse
import itertools
import random
import re
import sys
import time
from collections import deque, defaultdict

IDENTIFIER = r"[\w']+"
INPUT_PATTERN = re.compile(rf"INPUT\s*\(\s*({IDENTIFIER})\s*\)", re.IGNORECASE)
OUTPUT_PATTERN = re.compile(rf"OUTPUT\s*\(\s*({IDENTIFIER})\s*\)", re.IGNORECASE)
GATE_PATTERN = re.compile(rf"({IDENTIFIER})\s*=\s*(\w+)\s*\((.*?)\)", re.IGNORECASE)

SUPPORTED_GATES = {"AND", "BUFF", "NAND", "NOR", "NOT", "OR", "XOR"}


class Circuit:
    def __init__(self):
        self.node_to_id = {}
        self.id_to_node = []
        self.inputs = []
        self.outputs = []
        self.gates = []
        self.sorted_gates = []

    def get_id(self, name):
        if name not in self.node_to_id:
            self.node_to_id[name] = len(self.id_to_node)
            self.id_to_node.append(name)
        return self.node_to_id[name]

    def get_name(self, node_id):
        return self.id_to_node[node_id]


def parse_bench(file_path):
    circuit = Circuit()
    inputs_set = set()
    outputs_set = set()
    gate_by_out = {}

    with open(file_path, "r", encoding="utf-8") as bench_file:
        for line_number, raw_line in enumerate(bench_file, start=1):
            line = raw_line.split("#", 1)[0].strip()
            if not line or line.startswith("#"):
                continue

            input_match = INPUT_PATTERN.fullmatch(line)
            if input_match:
                node_name = input_match.group(1)
                if node_name in inputs_set:
                    raise ValueError(f"Line {line_number}: duplicate input '{node_name}'")
                if circuit.node_to_id.get(node_name) in gate_by_out:
                    raise ValueError(f"Line {line_number}: node '{node_name}' has multiple definitions")
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
                gate_input_names = [n.strip() for n in gate_match.group(3).split(",")]

                if gate_type not in SUPPORTED_GATES:
                    raise ValueError(f"Line {line_number}: unsupported gate '{gate_type}'")
                if not gate_match.group(3).strip():
                    raise ValueError(f"Line {line_number}: gate '{out_name}' has no inputs")
                if any(not re.fullmatch(IDENTIFIER, n) for n in gate_input_names):
                    raise ValueError(f"Line {line_number}: gate '{out_name}' has an invalid or empty input pin")
                if gate_type in {"NOT", "BUFF"} and len(gate_input_names) != 1:
                    raise ValueError(f"Line {line_number}: {gate_type} gate '{out_name}' must have exactly one input")

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

    if not circuit.inputs or not circuit.outputs:
        raise ValueError("Circuit must declare at least one input and one output")
    defined_nodes = set(circuit.inputs) | set(gate_by_out.keys())
    undefined = [circuit.get_name(i) for i in range(len(circuit.id_to_node)) if i not in defined_nodes]
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


def generate_faults(circuit, model="collapsed"):
    """Generates a programmatic list of faults for simulation."""
    if model not in {"collapsed", "full"}:
        raise ValueError("Fault model must be 'collapsed' or 'full'")
    faults = []
    input_faults = {"AND": 1, "NAND": 1, "OR": 0, "NOR": 0}
    output_faults = {"AND": 0, "NAND": 1, "OR": 1, "NOR": 0}

    # Primary Input stem faults
    for n in circuit.inputs:
        faults.append({'node': n, 'type': 'stem', 'val': 0, 'str': f"INPUT({circuit.get_name(n)}) - sa0"})
        faults.append({'node': n, 'type': 'stem', 'val': 1, 'str': f"INPUT({circuit.get_name(n)}) - sa1"})

    # Gate pin faults
    for gate in circuit.sorted_gates:
        g_type = gate["type"]
        out_id = gate["out"]
        out_name = circuit.get_name(out_id)

        if model == "full":
            for i, in_id in enumerate(gate["inputs"]):
                for val in (0, 1):
                    faults.append({'node': out_id, 'type': 'in', 'in_idx': i, 'val': val,
                                   'str': f"input {i+1}({circuit.get_name(in_id)}) - sa{val}"})
            for val in (0, 1):
                faults.append({'node': out_id, 'type': 'out', 'val': val, 'str': f"output - sa{val}"})
        elif g_type in input_faults:
            sa_val = input_faults[g_type]
            for i, in_id in enumerate(gate["inputs"]):
                in_name = circuit.get_name(in_id)
                faults.append({'node': out_id, 'type': 'in', 'in_idx': i, 'val': sa_val, 'str': f"input {i+1}({in_name}) - sa{sa_val}"})
            sa_out = output_faults[g_type]
            faults.append({'node': out_id, 'type': 'out', 'val': sa_out, 'str': f"output - sa{sa_out}"})
            
        elif g_type in {"NOT", "BUFF"}:
            faults.append({'node': out_id, 'type': 'out', 'val': 0, 'str': "output - sa0"})
            faults.append({'node': out_id, 'type': 'out', 'val': 1, 'str': "output - sa1"})
            
        else:  # XOR faults are retained at every pin
            for i, in_id in enumerate(gate["inputs"]):
                in_name = circuit.get_name(in_id)
                faults.append({'node': out_id, 'type': 'in', 'in_idx': i, 'val': 0, 'str': f"input {i+1}({in_name}) - sa0"})
                faults.append({'node': out_id, 'type': 'in', 'in_idx': i, 'val': 1, 'str': f"input {i+1}({in_name}) - sa1"})
            faults.append({'node': out_id, 'type': 'out', 'val': 0, 'str': "output - sa0"})
            faults.append({'node': out_id, 'type': 'out', 'val': 1, 'str': "output - sa1"})

    # Primary Output pin faults
    for n in circuit.outputs:
        faults.append({'node': n, 'type': 'out_stem', 'val': 0, 'str': f"OUTPUT({circuit.get_name(n)}) - sa0"})
        faults.append({'node': n, 'type': 'out_stem', 'val': 1, 'str': f"OUTPUT({circuit.get_name(n)}) - sa1"})

    return faults


def print_grouped_faults(circuit, faults, model="collapsed"):
    """Prints faults in the specific grouped format with injection IDs."""
    print(f"\n--- {model.title()} Pin Fault List ({len(faults)} total faults) ---")
    
    # Group by node for clean printing
    grouped = defaultdict(list)
    for i, f in enumerate(faults):
        if f['type'] in ('stem', 'out_stem'):
            grouped[f['str']].append(f"[{i}] {f['str']}")
        else:
            node_name = circuit.get_name(f['node'])
            grouped[node_name].append(f"[{i}] {f['str']}")

    for key, f_list in grouped.items():
        if "INPUT(" in key or "OUTPUT(" in key:
            print(f_list[0])
            if len(f_list) > 1: print(f_list[1])
        else:
            print(f"{key}: {', '.join(f_list)}")
    print("--------------------------------------------------")


def evaluate_circuit(circuit, input_values, injected_fault=None, trace=None):
    """Evaluate one vector; optionally append gate calculations to a trace list."""
    if set(input_values) != set(circuit.inputs):
        raise ValueError("Provide exactly the declared primary inputs")
    if any(val not in (0, 1) for val in input_values.values()):
        raise ValueError("Input values must be 0 or 1")
    values = [0] * len(circuit.id_to_node)
    
    # Apply primary inputs
    for in_id, val in input_values.items():
        values[in_id] = val

    # Inject Primary Input stem fault
    if injected_fault and injected_fault['type'] == 'stem':
        values[injected_fault['node']] = injected_fault['val']

    for gate in circuit.sorted_gates:
        g_type = gate["type"]
        out_id = gate["out"]
        ins = [values[i] for i in gate["inputs"]]

        # Inject gate input fault
        if injected_fault and injected_fault['type'] == 'in' and injected_fault['node'] == out_id:
            ins[injected_fault['in_idx']] = injected_fault['val']
            
        if g_type == "AND":
            res = ins[0]
            for val in ins[1:]: res &= val
        elif g_type == "OR":
            res = ins[0]
            for val in ins[1:]: res |= val
        elif g_type == "NAND":
            res = ins[0]
            for val in ins[1:]: res &= val
            res = 1 - res
        elif g_type == "NOR":
            res = ins[0]
            for val in ins[1:]: res |= val
            res = 1 - res
        elif g_type == "XOR":
            res = ins[0]
            for val in ins[1:]: res ^= val
        elif g_type == "NOT":
            res = 1 - ins[0]
        else:  # BUFF
            res = ins[0]

        # Inject gate output fault
        if injected_fault and injected_fault['type'] == 'out' and injected_fault['node'] == out_id:
            res = injected_fault['val']
            
        values[out_id] = res
        if trace is not None:
            trace.append({"node": out_id, "level": gate["level"], "gate": g_type,
                          "inputs": list(zip(gate["inputs"], ins)), "value": res})

    outputs = {out_id: values[out_id] for out_id in circuit.outputs}
    
    # Inject Primary Output pin fault
    if injected_fault and injected_fault['type'] == 'out_stem':
        if injected_fault['node'] in outputs:
            outputs[injected_fault['node']] = injected_fault['val']
            
    return outputs


def parse_vector(circuit, text, bit_order="msb-first"):
    """Binary follows declaration order; bit_order sets hex word significance."""
    width = len(circuit.inputs)
    text = text.strip()
    if text.lower().startswith("0x"):
        if not re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
            raise ValueError("Invalid hexadecimal vector")
        number = int(text, 16)
        if number >= (1 << width):
            raise ValueError(f"Vector exceeds the circuit's {width} inputs")
        bits = format(number, f"0{width}b")
        if bit_order == "lsb-first":
            bits = bits[::-1]
        elif bit_order != "msb-first":
            raise ValueError("Bit order must be msb-first or lsb-first")
    else:
        bits = text[2:] if text.lower().startswith("0b") else text
        if len(bits) != width or any(bit not in "01" for bit in bits):
            raise ValueError(f"Enter exactly {width} binary digits or a hex value starting with 0x")
    return dict(zip(circuit.inputs, map(int, bits)))


def parse_assignments(circuit, assignments):
    values = {}
    for assignment in assignments:
        if assignment.count("=") != 1:
            raise ValueError("Use --input NAME=BIT")
        name, bit = (part.strip() for part in assignment.split("="))
        node = circuit.node_to_id.get(name)
        if node not in circuit.inputs or bit not in {"0", "1"}:
            raise ValueError(f"Invalid input assignment: {assignment}")
        if node in values:
            raise ValueError(f"Repeated input assignment: {name}")
        values[node] = int(bit)
    if set(values) != set(circuit.inputs):
        raise ValueError("Provide --input NAME=BIT for every primary input")
    return values


def resolve_fault(circuit, text, faults):
    """Accept an ID or node[-source]-value, independently of fault collapsing."""
    text = text.strip()
    if text.isdigit():
        index = int(text)
        if index >= len(faults):
            raise ValueError(f"Fault ID must be between 0 and {len(faults)-1}")
        return faults[index]
    match = re.fullmatch(rf"({IDENTIFIER})-(?:({IDENTIFIER})-)?([01])", text)
    if not match:
        raise ValueError("Use a fault ID, node-0/node-1, or gate-source-0/gate-source-1")
    name, source, bit = match.groups()
    node = circuit.node_to_id.get(name)
    if node is None:
        raise ValueError(f"Unknown fault node: {name}")
    gate = next((g for g in circuit.gates if g["out"] == node), None)
    if source is not None:
        if gate is None:
            raise ValueError(f"Fault destination {name} is not a gate")
        pins = [i for i, pin in enumerate(gate["inputs"]) if circuit.get_name(pin) == source]
        if len(pins) != 1:
            raise ValueError(f"Gate {name} must have exactly one pin from {source}; use a full-list ID for repeated pins")
        return {"node": node, "type": "in", "in_idx": pins[0], "val": int(bit),
                "str": f"input {pins[0]+1}({source}) - sa{bit}"}
    kind = "stem" if node in circuit.inputs else "out"
    return {"node": node, "type": kind, "val": int(bit), "str": f"node - sa{bit}"}


def fault_label(circuit, fault):
    name = circuit.get_name(fault["node"])
    bit = fault["val"]
    if fault["type"] == "in":
        gate = next(g for g in circuit.gates if g["out"] == fault["node"])
        pin = fault["in_idx"]
        source = circuit.get_name(gate["inputs"][pin])
        return f"{name}-{source}-{bit} (gate input {pin+1})"
    kind = {"stem": "primary input stem", "out": "gate output",
            "out_stem": "primary output pin"}[fault["type"]]
    return f"{name}-{bit} ({kind})"


def prompt_for_input_values(circuit, bit_order="msb-first"):
    names = ", ".join(circuit.get_name(i) for i in circuit.inputs)
    while True:
        text = input(f"\nEnter binary or hex test vector ({names}): ")
        try:
            return parse_vector(circuit, text, bit_order)
        except ValueError as error:
            print(f"Error: {error}")


def print_summary(circuit):
    print(f"\n--- Circuit Benchmark Summary ---")
    print(f"Inputs  ({len(circuit.inputs)}): {', '.join([circuit.get_name(i) for i in circuit.inputs])}")
    print(f"Outputs ({len(circuit.outputs)}): {', '.join([circuit.get_name(i) for i in circuit.outputs])}")
    print(f"Gates   ({len(circuit.gates)})")


def print_vector(circuit, tv):
    print("Input vector (declaration order): " + "".join(str(tv[node]) for node in circuit.inputs))


def print_trace(circuit, trace):
    print("\nIntermediate nodes (dependency order):")
    print("level | node | gate | input nodes and values | result")
    for row in trace:
        pins = ", ".join(f"{circuit.get_name(node)}={bit}" for node, bit in row["inputs"])
        print(f"{row['level']:5} | {circuit.get_name(row['node'])} | {row['gate']} | {pins} | {row['value']}")


def simulate(circuit, tv, detailed=False):
    trace = [] if detailed else None
    started = time.perf_counter()
    outputs = evaluate_circuit(circuit, tv, trace=trace)
    print_vector(circuit, tv)
    if trace is not None:
        print_trace(circuit, trace)
    print("\nCircuit Simulation Results:")
    for node, bit in outputs.items():
        print(f"  {circuit.get_name(node)} = {bit}")
    print(f"(Completed in {time.perf_counter() - started:.5f}s)")
    return outputs


def simulate_single_fault(circuit, tv, fault):
    print_vector(circuit, tv)
    good = evaluate_circuit(circuit, tv)
    faulty = evaluate_circuit(circuit, tv, fault)
    print(f"\nFault Selected: {fault_label(circuit, fault)}")
    print("Good Machine Output:  ", {circuit.get_name(k): v for k, v in good.items()})
    print("Faulty Machine Output:", {circuit.get_name(k): v for k, v in faulty.items()})
    print(f"Result: {'DETECTED' if good != faulty else 'NOT DETECTED'}")
    return good != faulty


def simulate_all_faults(circuit, tv, faults, model="collapsed", summary_only=False):
    print_vector(circuit, tv)
    good = evaluate_circuit(circuit, tv)
    print("Good Machine Output:", {circuit.get_name(k): v for k, v in good.items()})
    started = time.perf_counter()
    detected = set()
    for index, fault in enumerate(faults):
        is_detected = evaluate_circuit(circuit, tv, fault) != good
        if is_detected:
            detected.add(index)
        if not summary_only:
            status = "DETECTED" if is_detected else "NOT DETECTED"
            print(f"[{index}] {fault_label(circuit, fault)}: {status}")
    print(f"\n--- {model.title()} Pin Fault Simulation Summary ---")
    print(f"Total Faults:     {len(faults)}")
    print(f"Faults Detected:  {len(detected)}")
    print(f"Fault Coverage:   {100 * len(detected) / len(faults) if faults else 0:.2f}%")
    print(f"(Completed in {time.perf_counter() - started:.5f}s)")
    return detected


def simulate_random_vectors(circuit, faults, count, seed, model="collapsed", bit_order="msb-first"):
    if count <= 0:
        raise ValueError("Random vector count must be positive")
    rng = random.Random(seed)
    cumulative = set()
    rows = []
    width = len(circuit.inputs)
    print(f"\nRandom vectors: {count}; seed: {seed}; hex bit order: {bit_order}")
    for index in range(count):
        number = rng.getrandbits(width)
        hex_vector = f"0x{number:0{(width + 3) // 4}X}"
        tv = parse_vector(circuit, hex_vector, bit_order)
        print(f"\nRandom vector {index+1}: {hex_vector}")
        found = simulate_all_faults(circuit, tv, faults, model, summary_only=True)
        cumulative |= found
        rows.append((hex_vector, len(found)))
    print("\nRandom vector detection counts (each vector tested independently):")
    for index, (hex_vector, detected) in enumerate(rows, start=1):
        print(f"{index:2}: {hex_vector} | {detected}/{len(faults)} detected")
    print(f"Cumulative distinct faults detected: {len(cumulative)}/{len(faults)}")
    return rows


def print_truth_table(circuit):
    if len(circuit.inputs) > 16:
        raise ValueError("Truth tables are limited to circuits with at most 16 inputs")
    print(" ".join(circuit.get_name(n) for n in circuit.inputs) + " | "
          + " ".join(circuit.get_name(n) for n in circuit.outputs))
    for bits in itertools.product((0, 1), repeat=len(circuit.inputs)):
        outputs = evaluate_circuit(circuit, dict(zip(circuit.inputs, bits)))
        print(" ".join(map(str, bits)) + " | " + " ".join(str(outputs[n]) for n in circuit.outputs))


def main():
    parser = argparse.ArgumentParser(description="Circuit and Fault Simulator")
    parser.add_argument("circuit_file", help="path to a .bench file")
    vectors = parser.add_mutually_exclusive_group()
    vectors.add_argument("--vector", help="binary in input declaration order, or a 0x hex word")
    vectors.add_argument("--input", action="append", help="NAME=BIT; repeat for every primary input")
    vectors.add_argument("--random", type=int, metavar="COUNT", help="test COUNT seeded random vectors against all faults")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--fault-list", action="store_true", help="print fault IDs and exit")
    modes.add_argument("--truth-table", action="store_true", help="print all good outputs; maximum 16 inputs")
    modes.add_argument("--fault", help="fault ID, node-value, or gate-source-value")
    modes.add_argument("--all-faults", action="store_true", help="test all listed faults")
    parser.add_argument("--fault-model", choices=("collapsed", "full"), default="collapsed")
    parser.add_argument("--bit-order", choices=("msb-first", "lsb-first"), default="msb-first",
                        help="hex significance only; binary always follows input declaration order")
    parser.add_argument("--trace", action="store_true", help="print every gate calculation during circuit simulation")
    parser.add_argument("--summary-only", action="store_true", help="hide individual rows for --all-faults")
    parser.add_argument("--seed", type=int, default=464, help="random seed (default: 464)")
    args = parser.parse_args()
    if args.random is not None and (args.fault_list or args.truth_table or args.fault):
        parser.error("--random cannot be combined with --fault-list, --truth-table, or --fault")
    if (args.fault_list or args.truth_table) and (args.vector is not None or args.input):
        parser.error("--fault-list and --truth-table do not take a test vector")
    if (args.fault or args.all_faults) and args.random is None and args.vector is None and args.input is None:
        parser.error("--fault and --all-faults need --vector or --input")
    try:
        circuit = parse_bench(args.circuit_file)
        faults = generate_faults(circuit, args.fault_model)
        print_summary(circuit)
        print(f"Fault model: {args.fault_model} pins ({len(faults)} entries)")
        print(f"Hex mapping: {args.bit_order}; binary follows input declaration order")
        if args.fault_list:
            print_grouped_faults(circuit, faults, args.fault_model)
        elif args.truth_table:
            print_truth_table(circuit)
        elif args.random is not None:
            simulate_random_vectors(circuit, faults, args.random, args.seed, args.fault_model, args.bit_order)
        elif args.vector is not None or args.input is not None:
            tv = parse_vector(circuit, args.vector, args.bit_order) if args.vector is not None else parse_assignments(circuit, args.input)
            if args.fault:
                simulate_single_fault(circuit, tv, resolve_fault(circuit, args.fault, faults))
            elif args.all_faults:
                simulate_all_faults(circuit, tv, faults, args.fault_model, args.summary_only)
            else:
                simulate(circuit, tv, args.trace)
        else:
            while True:
                print("\n" + "="*40)
                print("1. Fault listing")
                print("2. Circuit simulation")
                print("3. Fault simulation (Single fault against TV)")
                print("4. Fault simulation (All faults against TV)")
                print("5. Exit")
                print("6. Random vectors (all faults, summary)")
                choice = input("Select an option (1-6): ").strip()
                if choice == "1":
                    print_grouped_faults(circuit, faults, args.fault_model)
                elif choice in {"2", "3", "4"}:
                    tv = prompt_for_input_values(circuit, args.bit_order)
                    if choice == "2":
                        simulate(circuit, tv, detailed=True)
                    elif choice == "3":
                        try:
                            text = input(f"Enter fault ID [0-{len(faults)-1}] or named fault (e.g. y-1, 22-10-0): ")
                            fault = resolve_fault(circuit, text, faults)
                        except ValueError as error:
                            print(f"Error: {error}")
                            continue
                        simulate_single_fault(circuit, tv, fault)
                    else:
                        simulate_all_faults(circuit, tv, faults, args.fault_model, args.summary_only)
                elif choice == "5":
                    print("Exiting.")
                    break
                elif choice == "6":
                    try:
                        count = int(input("Random vector count [10]: ").strip() or "10")
                        seed = int(input(f"Seed [{args.seed}]: ").strip() or str(args.seed))
                        if count <= 0:
                            raise ValueError("Random vector count must be positive")
                    except ValueError as error:
                        print(f"Error: {error}")
                        continue
                    simulate_random_vectors(circuit, faults, count, seed, args.fault_model, args.bit_order)
                else:
                    print("Invalid choice.")
    except EOFError:
        print("\nInput closed. Exiting.")
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")
        return 130
    except (OSError, ValueError) as error:
        print(f"\nError: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
