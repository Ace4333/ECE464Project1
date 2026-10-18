"""Project 1 regression checks. Run with Python 3; no third-party packages needed.

Writes results.json and current CLI transcripts beside this file.
The reference evaluator parses BENCH independently and uses recursive Boolean
evaluation instead of the project's integer IDs and topological evaluator.
"""

import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.setrecursionlimit(10000)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = ROOT / "Project1_main.py"
SEED = 464


def reference_parse(path):
    inputs, outputs, gates = [], [], {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.upper().startswith("INPUT("):
            inputs.append(line[line.index("(") + 1:line.rindex(")")].strip())
        elif line.upper().startswith("OUTPUT("):
            outputs.append(line[line.index("(") + 1:line.rindex(")")].strip())
        else:
            name, rhs = line.split("=", 1)
            kind, pins = rhs.strip().split("(", 1)
            gates[name.strip()] = (kind.strip().upper(),
                                   [p.strip() for p in pins.rstrip(")").split(",")])
    return inputs, outputs, gates


def reference_evaluate(ref, bits, fault=None):
    inputs, outputs, gates = ref
    cache = dict(zip(inputs, map(bool, map(int, bits))))
    # fault = (kind, destination node name, input pin index or None, value).
    if fault and fault[0] == "stem":
        cache[fault[1]] = bool(fault[3])

    def value(node):
        if node in cache:
            return cache[node]
        kind, pins = gates[node]
        args = [value(pin) for pin in pins]
        if fault and fault[0] == "in" and fault[1] == node:
            args[fault[2]] = bool(fault[3])
        if kind in ("AND", "NAND"):
            result = all(args)
            if kind == "NAND":
                result = not result
        elif kind in ("OR", "NOR"):
            result = any(args)
            if kind == "NOR":
                result = not result
        elif kind == "XOR":
            result = sum(args) % 2 == 1
        elif kind == "NOT":
            result = not args[0]
        elif kind == "BUFF":
            result = args[0]
        else:
            raise AssertionError(kind)
        if fault and fault[0] == "out" and fault[1] == node:
            result = bool(fault[3])
        cache[node] = result
        return result

    result = {node: int(value(node)) for node in outputs}
    # Also evaluate nodes with no path to an output for intermediate-node QA.
    for node in gates:
        value(node)
    if fault and fault[0] == "out_stem":
        result[fault[1]] = fault[3]
    return result, {node: int(bit) for node, bit in cache.items()}


def main():
    before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("project_under_review", SOURCE)
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    data = {"python": sys.version, "seed": SEED, "source_sha256": before,
            "comparisons": 0, "benchmarks": {}, "assignment": {},
            "known_issues": [], "cli_runs": [], "full_fault_evaluations_compared": 0}

    def compare(actual, expected, label):
        if actual != expected:
            raise AssertionError(f"{label}: {actual!r} != {expected!r}")
        data["comparisons"] += 1

    def run_cli(name, stdin, tag, extra=(), expected_code=0):
        run = subprocess.run([sys.executable, str(SOURCE), str(ROOT / name), *extra],
                             input=stdin, text=True, capture_output=True, timeout=30)
        run.stdout = run.stdout.replace(str(ROOT), ".").replace(ROOT.as_posix(), ".")
        run.stderr = run.stderr.replace(str(ROOT), ".").replace(ROOT.as_posix(), ".")
        transcript = (
            f"BENCH: {name}\nArguments: {list(extra)!r}\n"
            f"Input supplied to menu:\n{stdin}\nExit code: {run.returncode}\n"
            f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}")
        (HERE / f"{tag}.txt").write_text(
            "\n".join(line.rstrip() for line in transcript.splitlines()) + "\n",
            encoding="utf-8", newline="\n")
        compare(run.returncode, expected_code, f"CLI {tag} exit")
        data["cli_runs"].append({"tag": tag, "exit_code": run.returncode})
        return run

    def named_outputs(circuit, tv, fault=None):
        return {circuit.get_name(node): bit for node, bit in
                project.evaluate_circuit(circuit, tv, fault).items()}

    rng = random.Random(SEED)
    for path in sorted(ROOT.glob("*.bench")):
        circuit = project.parse_bench(path)
        ref = reference_parse(path)
        faults = project.generate_faults(circuit)
        compare([circuit.get_name(i) for i in circuit.inputs], ref[0], path.name)
        compare([circuit.get_name(i) for i in circuit.outputs], ref[1], path.name)
        compare(len(circuit.sorted_gates), len(ref[2]), path.name)
        n = len(circuit.inputs)
        if n <= 5:
            vectors = ["".join(bits) for bits in itertools.product("01", repeat=n)]
        else:
            vectors = ["0" * n, "1" * n] + [
                format(rng.getrandbits(n), f"0{n}b") for _ in range(10)]
        for bits in vectors:
            tv = dict(zip(circuit.inputs, map(int, bits)))
            expected, _ = reference_evaluate(ref, bits)
            compare(named_outputs(circuit, tv), expected, f"{path.name} {bits}")
            if path.stem == "hw1":
                a, b, c = map(int, bits)
                hand = {"w": a & b & c,
                        "x": int((a and not b) or (not a and b and c)
                                 or (a and b and not c)),
                        "y": b ^ c, "z": 1 - c}
                compare(named_outputs(circuit, tv), hand, f"hw1 equations {bits}")
            if n <= 5:
                for f in faults:
                    rf = (f["type"], circuit.get_name(f["node"]),
                          f.get("in_idx"), f["val"])
                    expected, _ = reference_evaluate(ref, bits, rf)
                    compare(named_outputs(circuit, tv, f), expected,
                            f"{path.name} {bits} {rf}")
        data["benchmarks"][path.name] = {
            "inputs": n, "outputs": len(circuit.outputs),
            "gates": len(circuit.gates), "collapsed_faults": len(faults),
            "good_vectors_checked": len(vectors),
            "fault_evaluations_checked": len(vectors) * len(faults) if n <= 5 else 0}
        full_faults = project.generate_faults(circuit, "full")
        expected_full_count = 2 * (len(circuit.inputs) + len(circuit.outputs)
                                   + len(circuit.gates) + sum(len(g["inputs"]) for g in circuit.gates))
        compare(len(full_faults), expected_full_count, path.name + " full count")
        actual_sites = {(f["type"], f["node"], f.get("in_idx"), f["val"]) for f in full_faults}
        expected_sites = {(kind, node, None, bit) for kind, pins in
                          (("stem", circuit.inputs), ("out_stem", circuit.outputs))
                          for node in pins for bit in (0, 1)}
        for gate in circuit.gates:
            expected_sites.update(("out", gate["out"], None, bit) for bit in (0, 1))
            expected_sites.update(("in", gate["out"], pin, bit)
                                  for pin in range(len(gate["inputs"])) for bit in (0, 1))
        compare(actual_sites, expected_sites, path.name + " complete full fault sites")
        data["benchmarks"][path.name]["full_pin_faults"] = len(full_faults)
        if n <= 5:
            for bits in vectors:
                tv = project.parse_vector(circuit, bits)
                for f in full_faults:
                    rf = (f["type"], circuit.get_name(f["node"]), f.get("in_idx"), f["val"])
                    compare(named_outputs(circuit, tv, f), reference_evaluate(ref, bits, rf)[0],
                            f"{path.name} full {bits} {rf}")
                    data["full_fault_evaluations_compared"] += 1

    hw = project.parse_bench(ROOT / "hw1.bench")
    hf = project.generate_faults(hw)
    run_cli("hw1.bench", "1\n5\n", "01_hw1_fault_listing")
    run_cli("c432.bench", "1\n5\n", "02_c432_fault_listing")
    run_cli("hw1.bench", "2\n011\n2\n101\n5\n", "03_hw1_circuit_simulation")
    single_lines = []
    for bits in ("011", "101"):
        tv = dict(zip(hw.inputs, map(int, bits)))
        good = named_outputs(hw, tv)
        detected = [i for i, f in enumerate(hf) if named_outputs(hw, tv, f) != good]
        data["assignment"]["hw1_" + bits] = {
            "outputs": good, "detected": len(detected), "total": len(hf),
            "detected_ids": detected}
        data["assignment"]["hw1_" + bits]["full_detected"] = sum(
            named_outputs(hw, tv, f) != good for f in project.generate_faults(hw, "full"))
    for sa in (1, 0):
        fid = next(i for i, f in enumerate(hf) if f["type"] == "out_stem"
                   and hw.get_name(f["node"]) == "y" and f["val"] == sa)
        single_lines.extend(["3", "011", str(fid)])
    run_cli("hw1.bench", "\n".join(single_lines + ["5", ""]), "05_hw1_y_faults")
    run_cli("hw1.bench", "4\n011\n4\n101\n5\n", "07_hw1_all_faults")

    c17 = project.parse_bench(ROOT / "c17.bench")
    cf = project.generate_faults(c17)
    target = {"node": c17.node_to_id["22"], "type": "in", "in_idx": 0, "val": 0}
    compare(any(all(f.get(k) == v for k, v in target.items()) for f in cf), False,
            "collapsed list omits equivalent branch fault")
    resolved = project.resolve_fault(c17, "22-10-0", cf)
    compare({k: resolved[k] for k in target}, target, "named branch resolves outside collapsed list")
    data["assignment"]["c17_22-10-0"] = []
    for bits, expected_good, expected_bad in [
            ("00000", {"22": 0, "23": 0}, {"22": 1, "23": 0}),
            ("11111", {"22": 1, "23": 0}, {"22": 1, "23": 0})]:
        tv = dict(zip(c17.inputs, map(int, bits)))
        good = named_outputs(c17, tv)
        faulty = named_outputs(c17, tv, target)
        compare(good, expected_good, "c17 hand good")
        compare(faulty, expected_bad, "c17 hand faulty")
        data["assignment"]["c17_22-10-0"].append(
            {"input": bits, "good": good, "faulty": faulty, "detected": good != faulty})
    run = run_cli("c17.bench", "3\n00000\n22-10-0\n3\n11111\n22-10-0\n5\n",
                  "06_c17_branch_faults")
    compare(re.findall(r"Result: (.*)", run.stdout), ["DETECTED", "NOT DETECTED"],
            "c17 branch menu results")

    c6288 = project.parse_bench(ROOT / "c6288.bench")
    ref6288 = reference_parse(ROOT / "c6288.bench")
    # Derive output significance using products 2**i * 2**j. Validate the
    # resulting mapping separately against general integer multiplication.
    bit_nodes = {}
    for i in range(16):
        for j in range(16):
            tv = {node: 0 for node in c6288.inputs}
            tv[c6288.inputs[i]] = tv[c6288.inputs[16 + j]] = 1
            output = named_outputs(c6288, tv)
            active = [node for node, bit in output.items() if bit]
            compare(len(active), 1, "c6288 basis product one set bit")
            if i + j in bit_nodes:
                compare(active[0], bit_nodes[i + j], "c6288 consistent significance")
            bit_nodes[i + j] = active[0]
    remaining = set(ref6288[1]) - set(bit_nodes.values())
    compare(len(remaining), 1, "c6288 remaining carry output")
    bit_nodes[31] = remaining.pop()
    mul_rng = random.Random(SEED)
    products = [(0, 0), (65535, 65535), (7, 5), (40960, 57344)] + [
        (mul_rng.getrandbits(16), mul_rng.getrandbits(16)) for _ in range(64)]
    for a, b in products:
        tv = {node: (a >> i) & 1 for i, node in enumerate(c6288.inputs[:16])}
        tv.update({node: (b >> i) & 1 for i, node in enumerate(c6288.inputs[16:])})
        out = named_outputs(c6288, tv)
        number = sum(out[node] << i for i, node in bit_nodes.items())
        compare(number, a * b, f"c6288 integer multiplication {a}*{b}")
    bits = format(0x00050007, "032b")
    run_cli("c6288.bench", f"2\n{bits}\n5\n", "04_c6288_circuit_simulation")
    expected, nodes = reference_evaluate(ref6288, bits)
    compare(named_outputs(c6288, dict(zip(c6288.inputs, map(int, bits)))), expected,
            "c6288 assignment vector")
    trace = []
    project.evaluate_circuit(c6288, project.parse_vector(c6288, "0x00050007"), trace=trace)
    compare(len(trace), len(c6288.gates), "trace contains every gate")
    levels = {node: 0 for node in c6288.inputs}
    for row in trace:
        compare(row["value"], nodes[c6288.get_name(row["node"])], "trace result")
        compare(row["level"], max(levels[node] for node, _ in row["inputs"]) + 1, "trace level")
        levels[row["node"]] = row["level"]
        for node, bit in row["inputs"]:
            compare(bit, nodes[c6288.get_name(node)], "trace input")
    (HERE / "04_c6288_reference_nodes.csv").write_text(
        "node,value\n" + "".join(f"{node},{value}\n" for node, value in nodes.items()),
        encoding="utf-8", newline="\n")
    data["assignment"]["c6288_0x00050007"] = {
        "convention": "first declared input receives leftmost (MSB) binary digit",
        "binary": bits, "outputs": expected,
        "output_bit_to_node": bit_nodes, "multiplier_cases": len(products)}

    c432 = project.parse_bench(ROOT / "c432.bench")
    ref432 = reference_parse(ROOT / "c432.bench")
    ff = project.generate_faults(c432)
    full432 = project.generate_faults(c432, "full")
    rand432 = random.Random(SEED)
    vectors = [format(0xABCD1234, "036b")] + [
        format(rand432.getrandbits(36), "036b") for _ in range(10)]
    batch = []
    data["assignment"]["c432_vectors"] = []
    cumulative = set()
    for index, bits in enumerate(vectors):
        batch.extend(["4", bits])
        tv = dict(zip(c432.inputs, map(int, bits)))
        good = named_outputs(c432, tv)
        compare(good, reference_evaluate(ref432, bits)[0], "c432 good")
        detected = set()
        for i, f in enumerate(ff):
            rf = (f["type"], c432.get_name(f["node"]), f.get("in_idx"), f["val"])
            faulty = named_outputs(c432, tv, f)
            compare(faulty, reference_evaluate(ref432, bits, rf)[0], "c432 fault")
            if good != faulty:
                detected.add(i)
        if index:
            cumulative |= detected
        full_detected = 0
        for f in full432:
            rf = (f["type"], c432.get_name(f["node"]), f.get("in_idx"), f["val"])
            faulty = named_outputs(c432, tv, f)
            compare(faulty, reference_evaluate(ref432, bits, rf)[0], "c432 full fault")
            full_detected += faulty != good
            data["full_fault_evaluations_compared"] += 1
        data["assignment"]["c432_vectors"].append({
            "index": index, "hex": f"0x{int(bits, 2):09X}", "binary": bits,
            "outputs": good, "detected": len(detected), "total": len(ff),
            "full_detected": full_detected, "full_total": len(full432)})
    run = run_cli("c432.bench", "\n".join(batch + ["5", ""]), "08_c432_all_faults")
    compare([int(n) for n in re.findall(r"Faults Detected:\s+(\d+)", run.stdout)],
            [r["detected"] for r in data["assignment"]["c432_vectors"]],
            "menu and direct fault counts")
    data["assignment"]["c432_random_cumulative"] = len(cumulative)
    data["benchmarks"]["c432.bench"]["assignment_fault_evaluations_checked"] = len(ff) * len(vectors)
    data["fault_evaluations_compared"] = 400 + 1024 + len(ff) * len(vectors)

    # Exercise repaired interfaces and error handling as user-visible behavior.
    run_cli("hw1.bench", "", "check_cli_fault_list", ("--fault-list",))
    run = run_cli("hw1.bench", "", "check_cli_truth_table", ("--truth-table",))
    compare(len(re.findall(r"^[01] [01] [01] \|", run.stdout, re.MULTILINE)), 8, "truth rows")
    run = run_cli("hw1.bench", "", "check_cli_assignments",
                  ("--input", "a=0", "--input", "b=1", "--input", "c=1"))
    compare("  x = 1" in run.stdout and "  y = 0" in run.stdout, True, "named inputs")
    for tag, stdin in [("menu", ""), ("vector", "2\n"), ("fault_id", "3\n011\n"),
                       ("random_count", "6\n"), ("random_seed", "6\n10\n")]:
        run = run_cli("hw1.bench", stdin, "check_eof_" + tag)
        compare("Traceback" not in run.stderr and "Input closed" in run.stdout, True, tag)
    run = run_cli("c6288.bench", "", "check_hex_trace",
                  ("--vector", "0x00050007", "--trace"))
    compare(len(re.findall(r"^\s*\d+ \|", run.stdout, re.MULTILINE)), 2416, "CLI trace rows")
    run = run_cli("c17.bench", "", "check_named_fault_cli",
                  ("--vector", "00000", "--fault", "22-10-0"))
    compare("Result: DETECTED" in run.stdout, True, "CLI named fault")
    run = run_cli("hw1.bench", "", "check_all_fault_rows", ("--vector", "011", "--all-faults"))
    compare(len(re.findall(r"^\[\d+\] .+: (?:NOT )?DETECTED$", run.stdout, re.MULTILINE)),
            len(hf), "one identifiable row for every fault")
    compare(": NOT DETECTED" in run.stdout, True, "undetected rows visible")
    run = run_cli("c432.bench", "", "check_random_batch", ("--random", "10", "--seed", "464"))
    compare([int(n) for n in re.findall(r"Faults Detected:\s+(\d+)", run.stdout)],
            [row["detected"] for row in data["assignment"]["c432_vectors"][1:]], "seeded CLI counts")
    run = run_cli("hw1.bench", "", "check_full_list", ("--fault-list", "--fault-model", "full"))
    compare("Full Pin Fault List" in run.stdout, True, "full list label")
    run = run_cli("hw1.bench", "", "check_named_y0", ("--vector", "011", "--fault", "y-0"))
    compare("Result: NOT DETECTED" in run.stdout, True, "named y-0")
    run = run_cli("hw1.bench", "", "check_named_y1", ("--vector", "011", "--fault", "y-1"))
    compare("Result: DETECTED" in run.stdout, True, "named y-1")
    run = run_cli("c432.bench", "", "check_c432_hex_cli",
                  ("--vector", "0xABCD1234", "--all-faults", "--summary-only"))
    compare([int(n) for n in re.findall(r"Faults Detected:\s+(\d+)", run.stdout)], [47], "prescribed hex CLI")
    run = run_cli("hw1.bench", "", "check_full_simulation",
                  ("--vector", "011", "--all-faults", "--fault-model", "full", "--summary-only"))
    compare([int(n) for n in re.findall(r"Faults Detected:\s+(\d+)", run.stdout)],
            [data["assignment"]["hw1_011"]["full_detected"]], "full simulation CLI")
    run = run_cli("c432.bench", "6\n2\n464\n5\n", "check_random_menu")
    compare([int(n) for n in re.findall(r"Faults Detected:\s+(\d+)", run.stdout)], [42, 25], "random menu")
    compare(project.parse_vector(hw, "0x3"), project.parse_vector(hw, "011"), "short hex pad")
    compare(project.parse_vector(hw, "0x3", "lsb-first"), project.parse_vector(hw, "110"), "hex reverse")
    compare(project.parse_vector(hw, "011", "lsb-first"), project.parse_vector(hw, "011"), "binary order stable")
    for text in ("0x8", "0x-1", "0x", "0xG", "01", "012"):
        try:
            project.parse_vector(hw, text)
        except ValueError:
            data["comparisons"] += 1
        else:
            raise AssertionError("Invalid vector accepted: " + text)
    for text in ("99", "unknown-0", "x-a-0", "a-b-0", "y-2"):
        try:
            project.resolve_fault(hw, text, hf)
        except ValueError:
            data["comparisons"] += 1
        else:
            raise AssertionError("Invalid fault accepted: " + text)
    for tv in ({}, {hw.inputs[0]: 0}, {node: 2 for node in hw.inputs},
               {**dict.fromkeys(hw.inputs, 0), hw.node_to_id["x"]: 0}):
        try:
            project.evaluate_circuit(hw, tv)
        except ValueError:
            data["comparisons"] += 1
        else:
            raise AssertionError("Invalid input mapping accepted")
    for tag, name, extra in [
        ("overflow", "hw1.bench", ("--vector", "0x8")),
        ("missing_input", "hw1.bench", ("--input", "a=0")),
        ("duplicate_input", "hw1.bench", ("--input", "a=0", "--input", "a=1")),
        ("bad_fault", "c17.bench", ("--vector", "00000", "--fault", "22-99-0")),
        ("big_truth_table", "c432.bench", ("--truth-table",)),
        ("bad_random_count", "c432.bench", ("--random", "0")),
    ]:
        run = run_cli(name, "", "check_error_" + tag, extra, 2)
        compare("Traceback" not in run.stderr, True, tag)

    with tempfile.TemporaryDirectory(prefix="bench_review_", dir=HERE) as tmp:
        path = Path(tmp) / "case.bench"
        invalid = {
            "undefined": "INPUT(a)\nOUTPUT(z)\nz=AND(a,b)\n",
            "cycle": "INPUT(a)\nOUTPUT(x)\nx=NOT(y)\ny=NOT(x)\n",
            "duplicate_input": "INPUT(a)\nINPUT(a)\nOUTPUT(a)\n",
            "duplicate_gate": "INPUT(a)\nx=NOT(a)\nx=BUFF(a)\nOUTPUT(x)\n",
            "bad_unary_arity": "INPUT(a)\nINPUT(b)\nx=NOT(a,b)\nOUTPUT(x)\n",
            "unsupported_gate": "INPUT(a)\nx=UNKNOWN(a)\nOUTPUT(x)\n",
            "gate_before_input_multiple_driver": "x=NOT(a)\nINPUT(x)\nINPUT(a)\nOUTPUT(x)\n",
            "empty_gate_pin": "INPUT(a)\nINPUT(b)\nx=AND(a,,b)\nOUTPUT(x)\n",
            "empty_circuit": "# empty\n",
        }
        for name, content in invalid.items():
            path.write_text(content, encoding="utf-8")
            try:
                project.parse_bench(path)
            except ValueError:
                data["comparisons"] += 1
            else:
                raise AssertionError("Should reject " + name)

    compare(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), before, "source unchanged")
    data["source_unchanged"] = True
    (HERE / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS: {data['comparisons']} numerical, structural, and interface checks; "
          f"{len(data['benchmarks'])} benchmarks.")
    print("All regression checks passed. Hand-work and screenshot deliverables are separate.")
    print(f"Results and transcripts: {HERE}")


if __name__ == "__main__":
    main()
