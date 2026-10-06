import re
import sys

def parse_bench(file_path):
    inputs = []
    outputs = []
    gates = []

    # Regex patterns for line matching
    input_pattern  = re.compile(r"^INPUT\s*\(\s*([\w']+)\s*\)", re.IGNORECASE)
    output_pattern = re.compile(r"^OUTPUT\s*\(\s*([\w']+)\s*\)", re.IGNORECASE)
    gate_pattern   = re.compile(r"^([\w']+)\s*=\s*(\w+)\s*\((.*)\)", re.IGNORECASE)

    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Ignore empty lines and comment lines
            if not line or line.startswith('#'):
                continue

            in_match = input_pattern.match(line)
            if in_match:
                inputs.append(in_match.group(1))
                continue

            out_match = output_pattern.match(line)
            if out_match:
                outputs.append(out_match.group(1))
                continue

            gate_match = gate_pattern.match(line)
            if gate_match:
                out_node = gate_match.group(1)
                gate_type = gate_match.group(2).upper()
                in_nodes = [node.strip() for node in gate_match.group(3).split(',') if node.strip()]
                
                gates.append({
                    'out': out_node,
                    'type': gate_type,
                    'inputs': in_nodes,
                    'count': len(in_nodes)
                })

    gate_by_output = {gate['out']: gate for gate in gates}
    node_levels = {node: 0 for node in inputs}

    def get_level(node, visiting=None):
        if node in node_levels:
            return node_levels[node]
        if node not in gate_by_output:
            raise ValueError(f"Node '{node}' is used but never defined")

        visiting = set() if visiting is None else visiting
        if node in visiting:
            raise ValueError(f"Cycle detected while finding level for '{node}'")

        visiting.add(node)
        gate = gate_by_output[node]
        input_levels = [get_level(input_node, visiting) for input_node in gate['inputs']]
        visiting.remove(node)
        node_levels[node] = 1 + max(input_levels, default=0)
        return node_levels[node]

    for gate in gates:
        gate['level'] = get_level(gate['out'])

    gates.sort(key=lambda gate: gate['level'])

    # Print nicely formatted results
    print("--- Circuit Benchmark Summary ---")
    print(f"Inputs  ({len(inputs)}): {', '.join(inputs)}")
    print(f"Outputs ({len(outputs)}): {', '.join(outputs)}")
    print("\nNodes (level order):")
    for node in inputs:
        output_label = " OUTPUT" if node in outputs else ""
        print(f"{node} (level 0): INPUT{output_label}")

    for g in gates:
        inputs_str = ", ".join(g['inputs'])
        output_label = " OUTPUT" if g['out'] in outputs else ""
        print(f"{g['out']} (level {g['level']}): {g['count']}-input {g['type']} of {inputs_str}{output_label}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_bench.py <circuit_file.bench>")
    else:
        parse_bench(sys.argv[1])