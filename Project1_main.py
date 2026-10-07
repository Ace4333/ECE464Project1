import argparse
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


def generate_faults(circuit):
    """Generates a programmatic list of all collapsed faults for simulation."""
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

        if g_type in input_faults:
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


def print_grouped_faults(circuit, faults):
    """Prints faults in the specific grouped format with injection IDs."""
    print(f"\n--- Collapsed Fault List ({len(faults)} total faults) ---")
    
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


def evaluate_circuit(circuit, input_values, injected_fault=None):
    """Evaluates the circuit, optionally injecting a single stuck-at fault."""
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

    outputs = {out_id: values[out_id] for out_id in circuit.outputs}
    
    # Inject Primary Output pin fault
    if injected_fault and injected_fault['type'] == 'out_stem':
        if injected_fault['node'] in outputs:
            outputs[injected_fault['node']] = injected_fault['val']
            
    return outputs


def prompt_for_input_values(circuit):
    input_names = [circuit.get_name(i) for i in circuit.inputs]
    input_order = ", ".join(input_names)
    while True:
        try:
            bit_string = input(f"\nEnter test vector ({input_order}): ").strip()
        except EOFError:
            print()
            return None
        if len(bit_string) == len(circuit.inputs) and all(b in {"0", "1"} for b in bit_string):
            return {circuit.get_id(n): int(b) for n, b in zip(input_names, bit_string)}
        print(f"Error: Enter exactly {len(circuit.inputs)} bits using only 0 and 1.")


def print_summary(circuit):
    print(f"\n--- Circuit Benchmark Summary ---")
    print(f"Inputs  ({len(circuit.inputs)}): {', '.join([circuit.get_name(i) for i in circuit.inputs])}")
    print(f"Outputs ({len(circuit.outputs)}): {', '.join([circuit.get_name(i) for i in circuit.outputs])}")
    print(f"Gates   ({len(circuit.gates)})")


def main():
    parser = argparse.ArgumentParser(description="Circuit and Fault Simulator")
    parser.add_argument("circuit_file", help="path to a .bench file")
    args = parser.parse_args()

    try:
        circuit = parse_bench(args.circuit_file)
        faults = generate_faults(circuit)
        print_summary(circuit)
        
        while True:
            print("\n" + "="*40)
            print("1. Fault listing")
            print("2. Circuit simulation")
            print("3. Fault simulation (Single fault against TV)")
            print("4. Fault simulation (All faults against TV)")
            print("5. Exit")
            choice = input("Select an option (1-5): ").strip()

            if choice == '1':
                print_grouped_faults(circuit, faults)

            elif choice == '2':
                tv = prompt_for_input_values(circuit)
                if not tv: continue
                
                start_time = time.time()
                outputs = evaluate_circuit(circuit, tv)
                elapsed = time.time() - start_time
                
                print("\nCircuit Simulation Results:")
                for out_id in circuit.outputs:
                    print(f"  {circuit.get_name(out_id)} = {outputs[out_id]}")
                print(f"(Completed in {elapsed:.5f}s)")

            elif choice == '3':
                tv = prompt_for_input_values(circuit)
                if not tv: continue
                
                try:
                    f_id = int(input(f"Enter Fault ID [0 to {len(faults)-1}] (Run Option 1 to see IDs): ").strip())
                    if f_id < 0 or f_id >= len(faults): raise ValueError
                except ValueError:
                    print("Invalid Fault ID.")
                    continue
                    
                target_fault = faults[f_id]
                
                good_machine = evaluate_circuit(circuit, tv)
                faulty_machine = evaluate_circuit(circuit, tv, injected_fault=target_fault)
                
                detected = good_machine != faulty_machine
                
                print(f"\nFault Selected: {circuit.get_name(target_fault['node'])} {target_fault['str']}")
                print(f"Good Machine Output:   ", {circuit.get_name(k): v for k, v in good_machine.items()})
                print(f"Faulty Machine Output: ", {circuit.get_name(k): v for k, v in faulty_machine.items()})
                print(f"Result: {'DETECTED' if detected else 'NOT DETECTED'}")

            elif choice == '4':
                tv = prompt_for_input_values(circuit)
                if not tv: continue
                
                print("\nRunning full fault simulation...")
                start_time = time.time()
                
                good_machine = evaluate_circuit(circuit, tv)
                detected_count = 0
                
                for f in faults:
                    faulty_machine = evaluate_circuit(circuit, tv, injected_fault=f)
                    if faulty_machine != good_machine:
                        detected_count += 1
                        
                elapsed = time.time() - start_time
                coverage = (detected_count / len(faults)) * 100
                
                print(f"\n--- Fault Simulation Summary ---")
                print(f"Total Faults:     {len(faults)}")
                print(f"Faults Detected:  {detected_count}")
                print(f"Fault Coverage:   {coverage:.2f}%")
                print(f"(Completed in {elapsed:.5f}s)")

            elif choice == '5':
                print("Exiting.")
                break
            else:
                print("Invalid choice.")

    except (OSError, ValueError, KeyboardInterrupt) as error:
        print(f"\nError: {error}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())