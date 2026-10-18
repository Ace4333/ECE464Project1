# ECE 464 Project 1 verification

Reviewed October 18, 2026. **The tested circuit and fault calculations are correct, but the current program does not yet demonstrate every software requirement in the screenshots.**

Scope: reviewed the one Python program, README, and all 12 supplied BENCH files. Used the screenshots as assignment criteria. The separate Canvas assignment was not provided. The screenshot's request for hand work and PDF screenshots was treated as assignment context; this review does not create or submit those deliverables.

`Project1_main.py`, the BENCH files, and the existing README were left unchanged. Added this report and a reproducible validation folder. The validator records a SHA-256 check that the source remains unchanged.

## Findings and suggested fixes

### 1. The menu cannot select the exact required c17 branch fault

**Assignment impact: software item 6.** In [fault generation](Project1_main.py#L137), NAND input pins retain only stuck-at-1 faults. The fault `22-10-0` is therefore absent from the generated list, while [single-fault selection](Project1_main.py#L320) accepts only an ID from that list.

The evaluator already supports this branch fault correctly. The review called it directly with:

```python
fault = {
    "node": circuit.node_to_id["22"],
    "type": "in",
    "in_idx": 0,  # Gate 22's first input is node 10.
    "val": 0,
}
outputs = evaluate_circuit(circuit, input_values, fault)
```

Suggested fix: accept named faults such as `22-10-0`, validate the destination gate and source pin, and construct the fault independently of the collapsed fault list. Keep ID selection as an alternative. Also support a node fault such as `y-0` or `y-1` without requiring the user to find an ID.

This is a selection limitation, not an incorrect NAND calculation. For this NAND, `22-10-0` is equivalent to gate 22's output stuck at 1, which is retained. An equivalent-fault demonstration should explicitly identify that mapping; selecting the retained `22-10-1` input fault would be the wrong fault.

### 2. c6288 simulation omits the required intermediate nodes

**Assignment impact: software item 4.** [The evaluator](Project1_main.py#L250) returns only primary outputs. [Menu option 2](Project1_main.py#L311) consequently prints only those outputs. It does not print intermediate nodes, gate inputs, levels, or gate types.

Suggested fix: add an optional trace return or callback while preserving the default output dictionary. Print a table such as `level | node | gate | input nodes and values | result`, using the existing `sorted_gates` and `gate['level']`. Add a detailed mode for c6288 so enough intermediate calculations can be captured for the assignment.

The review saved independent intermediate-node values in `verification/04_c6288_reference_nodes.csv`. These are reference calculations, not output that the original program printed.

### 3. All-fault output does not identify each fault, and hides undetected faults

**Assignment impact: presenting software items 7 and 8.** [Menu option 4](Project1_main.py#L349) prints `f['str']` without its fault ID or gate node. Many different faults appear as exactly `output - sa0: DETECTED`. The same code prints a row only when the fault is detected, so `NOT DETECTED` can never appear.

The numerical detection count is correct for the current generated list. The detailed output is difficult to audit and does not show a result for every fault.

Suggested fix: enumerate the faults and print one row per fault, with ID, gate/node, pin or stem, stuck value, and detection status. Move printing outside the detection-only condition. For example, report `[21] e output sa0: DETECTED` rather than `output - sa0: DETECTED`. Optionally offer a detected-only filter for large lists.

### 4. Hex vectors need manual conversion, with an explicit bit-order convention

**Assignment impact: convenience and reproducibility for items 4 and 8.** [The input prompt](Project1_main.py#L269) accepts exactly one binary digit per declared primary input. Literal `0x00050007` is rejected. This does not prevent simulation after manual conversion.

c432 has **36 inputs**, although `0xABCD1234` contains 32 significant positions. Under a convention where the first declared input receives the leftmost digit, the required binary entries are:

| Benchmark | Hex value | Binary entry |
|---|---|---|
| c6288 | `0x00050007` | `00000000000001010000000000000111` |
| c432 | `0xABCD1234` | `000010101011110011010001001000110100` |

Suggested fix: support both binary and `0x` input. For hex, parse with `int(text, 16)`, reject negative or overflowing values, then zero-pad with `format(value, f'0{len(circuit.inputs)}b')`. Document which end maps to the first declared input.

The screenshots do not establish how hex significance maps onto input declarations, so this review explicitly used **first declared input = leftmost binary digit**. If the separate Canvas specification assigns the least significant bit to the first input, reverse the mapping. That changes the test vector and its results.

c6288 is a useful cross-check: input declarations 1 through 256 correspond to the first operand's bits 0 through 15, and 273 through 528 to the second operand's bits 0 through 15. This was verified using basis inputs and integer multiplication. With the leftmost-digit convention above, the operand values are 40960 and 57344, and their product is `0x8C000000`. With the first-input-as-LSB convention, the same hex word represents operands 7 and 5 and yields `0x00000023`.

Do not directly interpret c6288's declared output order as a normal binary integer: outputs through 6280 represent bits 0 through 29, **6288 is bit 30**, and **6287 is bit 31**. Node-by-node output avoids that ambiguity.

### 5. README examples do not match the CLI

[README lines 16 onward](README.md#L16) document `--input`, `--truth-table`, and `--fault-list`. [The argument parser](Project1_main.py#L281) implements none of them. All three commands were run and failed with exit code 2 and `unrecognized arguments`.

The README also says the initial command shows nodes in dependency order, whereas the program shows a benchmark summary and menu.

Suggested fix: either implement the documented flags or update the README to describe the existing menu. For the current program, run `python Project1_main.py hw1.bench` from the inner project directory, then choose menu options 1 through 5.

### 6. EOF causes an uncaught traceback

[The menu prompt](Project1_main.py#L298) and [fault-ID prompt](Project1_main.py#L321) call `input()` without catching `EOFError`. The outer handler does not catch it either. Both failures were reproduced. The vector prompt catches EOF but returns to the menu, where EOF then crashes.

Suggested fix: handle EOF as a clean exit at the outer interaction boundary. When the vector prompt returns `None`, exit rather than returning to a menu that can no longer read input. This matters for redirected input and automated runs.

### 7. Parser validation has two edge cases

These do not affect the supplied valid benchmarks, but both were reproduced:

- [Input declaration checking](Project1_main.py#L49) rejects duplicate `INPUT` declarations but accepts a node already defined as a gate output if `INPUT` appears later. `x=NOT(a)` followed by `INPUT(x)` and `INPUT(a)` is accepted and the gate overwrites the primary input. Check for an existing gate driver in the `INPUT` branch too, or validate driver uniqueness after parsing all lines.
- [Gate argument parsing](Project1_main.py#L68) silently removes empty tokens, so `AND(a,,b)` is accepted as `AND(a,b)`. Reject empty argument tokens before constructing the input list.

The parser did correctly reject undefined nodes, cycles, repeated input declarations, repeated gate outputs, invalid unary-gate arity, and unsupported gate names in the tested cases. It also accepts an empty circuit; rejecting that early would give a clearer user error.

## Fault-model qualification

The current list uses local gate fault equivalence to collapse faults, and retains separate primary-input, primary-output, and gate-pin entries. Its totals are **50 for hw1**, **32 for c17**, and **636 for c432**. These match the implemented policy; they are not an uncollapsed full list or a globally deduplicated set of fault-equivalence classes.

Some retained entries have identical behavior, such as a final gate's output fault and its separate primary-output pin fault. Their detection counts contribute separately under the current model. This is not a computation error, but the fault universe must be stated whenever reporting coverage.

The hand-work screenshot explicitly asks for a **full fault list**. The software screenshot only says “fault listing.” Check the separate assignment specification before treating the collapsed list as the full-list deliverable. Suggested improvement: provide explicitly labeled full and collapsed modes, state how stems, fanout branches, and primary-output pins are counted, and allow named single-fault injection in either mode. Changing the model changes the counts below.

## Assignment cases actually checked

| Software item | Result |
|---|---|
| 1. hw1 fault listing | Menu works; prints 50 collapsed entries with IDs. |
| 2. c432 fault listing | Menu works; prints 636 collapsed entries with IDs. |
| 3. hw1 at 011 and 101 | Correct: output order `w,x,y,z` gives `0100` and `0110`. |
| 4. c6288 at 0x00050007 | Correct outputs after explicit binary conversion; intermediate-node display is missing. |
| 5. hw1 y-1 and y-0 at 011 | Correct using primary-output IDs 47 and 46: y-1 detected; y-0 not detected. |
| 6. c17 22-10-0 | Correct through direct function injection; exact branch is unavailable in the menu. |
| 7. hw1 all generated faults | 011 detects 17/50 (34%); 101 detects 14/50 (28%). Detailed labels need improvement. |
| 8. c432 prescribed and random vectors | Correct counts for the 636-entry model, after binary conversion. Random vectors were generated by the validator and supplied to the menu; the original program has no random-vector batch mode. |

c17 direct-injection results, output order `22,23`:

| Input order 1,2,3,6,7 | Good outputs | Faulty outputs | 22-10-0 detected? |
|---|---|---|---|
| `00000` | `00` | `10` | Yes |
| `11111` | `10` | `10` | No |

For c6288 under the stated leftmost-digit convention, the only primary outputs equal to 1 are **6250, 6260, and 6287**. All other primary outputs are 0.

c432 results below use 36-bit vectors, the stated leftmost-digit convention, and the current collapsed list. Random vectors use Python `random.Random(464).getrandbits(36)`.

| Case | Input hex, padded to 36 bits | Faults detected / 636 |
|---|---|---|
| Prescribed | `0x0ABCD1234` | 47 |
| Random 1 | `0x2459CA087` | 42 |
| Random 2 | `0xD8C3CC4AE` | 25 |
| Random 3 | `0x39E21FDD0` | 74 |
| Random 4 | `0xC3AF3F9A4` | 57 |
| Random 5 | `0x84772741C` | 41 |
| Random 6 | `0xE2A39FA07` | 83 |
| Random 7 | `0xD57FD3254` | 61 |
| Random 8 | `0x8D81309FA` | 42 |
| Random 9 | `0x1EEAEC149` | 47 |
| Random 10 | `0x46F5E8BE6` | 47 |

The 10 random vectors collectively detect 277 distinct entries. Per-vector counts above are independent; they do not drop faults detected by previous vectors.

## Verification method and limits

The validator completed **9,218 comparisons and defect-reproduction checks**, including:

- Parsing all 12 provided benchmarks and comparing input/output order and gate count with an independent parser.
- Comparing good-machine outputs for all 8 hw1 vectors, all 32 c17 vectors, and 12 vectors for each of the other 10 benchmarks (all zero, all one, and 10 seeded random vectors).
- Comparing every generated fault for every hw1 and c17 vector: 400 + 1,024 faulty evaluations.
- Comparing all 636 c432 faults for the prescribed vector and each of 10 seeded random vectors: 6,996 faulty evaluations. Across those three benchmarks, **8,420 faulty evaluations** matched the independent evaluator.
- Checking hw1 against hand-derived Boolean equations and the two required c17 cases against explicit expected outputs.
- Checking c6288 with 256 one-hot operand pairs to establish output significance, followed by 68 integer-multiplication cases, including maximum operands and 64 seeded random operand pairs.
- Running the existing menu in subprocesses, saving raw transcripts, and matching c432 menu counts against independently checked direct calls.

The independent evaluator uses node names, recursive dependencies, Boolean `all`/`any`, and parity. It does not call the project's parser or gate evaluator. Faults under comparison are the faults generated by the project; this verifies their simulation, not that the fault list matches an unseen instructor specification. Large benchmarks were sampled, not exhaustively tested. Their full fault lists were generated, but exhaustive fault simulations were limited to hw1/c17 and the specified c432 vectors.

Saved evidence:

- [Validator](verification/verify_project.py)
- [Machine-readable results](verification/results.json)
- [hw1 circuit menu transcript](verification/03_hw1_circuit_simulation.txt)
- [hw1 single-fault menu transcript](verification/05_hw1_y_faults.txt)
- [c17 direct-function evidence](verification/06_c17_direct_function_check.txt)
- [c6288 menu transcript](verification/04_c6288_circuit_simulation.txt)
- [c6288 independent reference-node values](verification/04_c6288_reference_nodes.csv)
- [c432 all-fault menu transcript](verification/08_c432_all_faults.txt)

Run from the inner project directory with a working Python 3 installation:

```text
python verification/verify_project.py
```

Known defects are recorded as observed behavior. The validator's PASS means its comparisons and reproductions succeeded; it does **not** mean those defects are fixed or that the assignment is ready to submit.
