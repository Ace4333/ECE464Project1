# project 1 verification

updated october 18, 2026. the identified script issues are fixed and the regression checks pass. the supplied circuit files are unchanged.

## fixes

- named node and branch faults work in the menu and cli, including y-0, y-1, and 22-10-0. selection is independent of the collapsed list.
- c6288 prints every intermediate gate, input value, level, and result using --trace; menu circuit simulation shows the same detail.
- all-fault output includes each fault id, destination node, pin or stem, and detected or not detected status.
- binary and hex vectors are supported with overflow checks and explicit msb-first or lsb-first hex mapping.
- seeded random batches report per-vector counts and cumulative distinct detections.
- --input, --truth-table, and --fault-list now match the readme.
- eof exits cleanly. duplicate drivers, empty gate pins, empty circuits, and incomplete/nonbinary input maps are rejected.
- a full pin-fault mode is available alongside the original collapsed mode.

## verification

33,081 numerical, structural, and interface checks passed across all 12 supplied benchmarks. this includes 8,420 collapsed-fault evaluations and 14,146 full pin-fault evaluations compared with an independent recursive boolean evaluator.

hw1 and c17 were checked for every input vector and every fault in both models. c432 was checked against every fault in both models for the prescribed vector and 10 seeded random vectors. larger benchmarks used sampled good-machine vectors. c6288 also passed 68 integer-multiplication cases after output significance was established using 256 basis input pairs.

all 2,416 c6288 trace rows were checked against independent node values, input values, and dependency levels. cli checks cover the required c17 branch, hex input, full fault mode, named inputs, truth tables, seeded random counts, invalid inputs, and eof at each prompt.

## required results

| case | verified result |
|---|---|
| hw1 input 011 | wxyz = 0100; 17/50 collapsed faults detected; 30/86 full pin faults detected |
| hw1 input 101 | wxyz = 0110; 14/50 collapsed faults detected; 23/86 full pin faults detected |
| hw1 input 011, y-1 | detected; wxyz changes from 0100 to 0110 |
| hw1 input 011, y-0 | not detected; wxyz stays 0100 |
| c17 input 00000, 22-10-0 | detected; outputs 22,23 change from 00 to 10 |
| c17 input 11111, 22-10-0 | not detected; outputs 22,23 stay 10 |
| c432 input 0xABCD1234 | 47/636 collapsed faults detected; 100/1078 full pin faults detected |

c432 random counts with seed 464, collapsed model: 42, 25, 74, 57, 41, 83, 61, 42, 47, 47. the 10 vectors collectively detect 277/636 distinct entries. vectors and outputs are recorded in [results](verification/results.json).

hex results use first-declared-input = leftmost binary digit by default. the screenshots did not specify hex significance; --bit-order lsb-first supports the alternative. binary declaration order is always explicit.

for c6288 at 0x00050007 using the default mapping, only outputs 6250, 6260, and 6287 are 1. c6288 output 6288 is product bit 30 and output 6287 is bit 31, so declaration order must not be read as a normal binary integer.

## evidence and remaining submission work

[readme](README.md) lists the commands for all eight software items. [validator](verification/verify_project.py) reproduces the checks and refreshes the program transcripts. [c17 transcript](verification/06_c17_branch_faults.txt), [c6288 trace](verification/check_hex_trace.txt), and [random batch](verification/check_random_batch.txt) demonstrate the repaired features.

the hand-work section and organized screenshot pdfs still need to be prepared for canvas. these transcripts are text output, not screenshot pdfs. no submission has been made. the separate canvas specification was not available, so the team must use its required fault model and hex convention; the program labels both explicitly.
