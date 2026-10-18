"""Read-only project review. Run with Python 3; no third-party packages needed.

Writes results.json and CLI transcripts beside this file. Known interface and
parser defects are recorded separately from numerical comparison failures.
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
            "known_issues": [], "cli_runs": []}

    def compare(actual, expected, label):
        if actual != expected:
            raise AssertionError(f"{label}: {actual!r} != {expected!r}")
        data["comparisons"] += 1

    def run_cli(name, stdin, tag, extra=(), expected_code=0):
        run = subprocess.run([sys.executable, str(SOURCE), str(ROOT / name), *extra],
                             input=stdin, text=True, capture_output=True, timeout=30)
        run.stdout = run.stdout.replace(str(ROOT), ".").replace(ROOT.as_posix(), ".")
        run.stderr = run.stderr.replace(str(ROOT), ".").replace(ROOT.as_posix(), ".")
        (HERE / f"{tag}.txt").write_text(
            f"BENCH: {name}\nArguments: {list(extra)!r}\n"
            f"Input supplied to menu:\n{stdin}\nExit code: {run.returncode}\n"
            f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}", encoding="utf-8")
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
            "required 22-10-0 missing from selectable list")
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
    (HERE / "06_c17_direct_function_check.txt").write_text(
        "Direct evaluate_circuit() checks, not menu output. The exact branch fault\n"
        "22-10-0 is absent from generate_faults(), so the current menu cannot select it.\n\n"
        + json.dumps(data["assignment"]["c17_22-10-0"], indent=2) + "\n",
        encoding="utf-8")

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
    (HERE / "04_c6288_reference_nodes.csv").write_text(
        "node,value\n" + "".join(f"{node},{value}\n" for node, value in nodes.items()),
        encoding="utf-8")
    data["assignment"]["c6288_0x00050007"] = {
        "convention": "first declared input receives leftmost (MSB) binary digit",
        "binary": bits, "outputs": expected,
        "output_bit_to_node": bit_nodes, "multiplier_cases": len(products)}

    c432 = project.parse_bench(ROOT / "c432.bench")
    ref432 = reference_parse(ROOT / "c432.bench")
    ff = project.generate_faults(c432)
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
        data["assignment"]["c432_vectors"].append({
            "index": index, "hex": f"0x{int(bits, 2):09X}", "binary": bits,
            "outputs": good, "detected": len(detected), "total": len(ff)})
    run = run_cli("c432.bench", "\n".join(batch + ["5", ""]), "08_c432_all_faults")
    compare([int(n) for n in re.findall(r"Faults Detected:\s+(\d+)", run.stdout)],
            [r["detected"] for r in data["assignment"]["c432_vectors"]],
            "menu and direct fault counts")
    data["assignment"]["c432_random_cumulative"] = len(cumulative)
    data["benchmarks"]["c432.bench"]["assignment_fault_evaluations_checked"] = len(ff) * len(vectors)
    data["fault_evaluations_compared"] = 400 + 1024 + len(ff) * len(vectors)

    # Reproduce defects explicitly; these are observations, not passing features.
    for flag in ("--fault-list", "--truth-table", "--input"):
        extra = (flag, "a=0") if flag == "--input" else (flag,)
        run = run_cli("hw1.bench", "", "issue_cli_" + flag[2:], extra, 2)
        compare("unrecognized arguments" in run.stderr, True, "stale README flag")
    for tag, stdin in [("issue_eof_menu", ""), ("issue_eof_fault_id", "3\n011\n")]:
        run = run_cli("hw1.bench", stdin, tag, expected_code=1)
        compare("EOFError" in run.stderr, True, tag)
    run = run_cli("c6288.bench", "2\n0x00050007\n" + format(0x50007, "032b") + "\n5\n",
                  "issue_hex_input")
    compare("Enter exactly 32 bits" in run.stdout, True, "hex rejected")

    with tempfile.TemporaryDirectory(prefix="bench_review_", dir=HERE) as tmp:
        path = Path(tmp) / "case.bench"
        invalid = {
            "undefined": "INPUT(a)\nOUTPUT(z)\nz=AND(a,b)\n",
            "cycle": "INPUT(a)\nOUTPUT(x)\nx=NOT(y)\ny=NOT(x)\n",
            "duplicate_input": "INPUT(a)\nINPUT(a)\nOUTPUT(a)\n",
            "duplicate_gate": "INPUT(a)\nx=NOT(a)\nx=BUFF(a)\nOUTPUT(x)\n",
            "bad_unary_arity": "INPUT(a)\nINPUT(b)\nx=NOT(a,b)\nOUTPUT(x)\n",
            "unsupported_gate": "INPUT(a)\nx=UNKNOWN(a)\nOUTPUT(x)\n",
        }
        for name, content in invalid.items():
            path.write_text(content, encoding="utf-8")
            try:
                project.parse_bench(path)
            except ValueError:
                data["comparisons"] += 1
            else:
                raise AssertionError("Should reject " + name)
        for name, content in {
            "gate_before_input_multiple_driver": "x=NOT(a)\nINPUT(x)\nINPUT(a)\nOUTPUT(x)\n",
            "empty_gate_pin": "INPUT(a)\nINPUT(b)\nx=AND(a,,b)\nOUTPUT(x)\n",
            "empty_circuit": "# empty\n",
        }.items():
            path.write_text(content, encoding="utf-8")
            project.parse_bench(path)
            data["known_issues"].append({"name": name, "invalid_bench_accepted": content})

    compare(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), before, "source unchanged")
    data["source_unchanged"] = True
    (HERE / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {data['comparisons']} numerical/structural/reproduction checks; "
          f"{len(data['benchmarks'])} benchmarks.")
    print("Known defects are reproduced separately; this is not assignment sign-off.")
    print(f"Results and transcripts: {HERE}")


if __name__ == "__main__":
    main()
