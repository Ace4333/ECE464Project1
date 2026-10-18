# ece 464 project 1

circuit and single stuck-at fault simulation. `hw1.bench` is a test circuit filename; the assignment is project 1.

## run

requires python 3 and no extra packages. run commands from this directory.

```text
python Project1_main.py hw1.bench
```

the menu supports fault listing, circuit simulation with intermediate nodes, named or numbered single faults, all faults, and seeded random vectors. option 5 exits; option 6 runs random vectors. eof exits cleanly.

## required software cases

1. hw1 fault listing:

```text
python Project1_main.py hw1.bench --fault-list
```

2. c432 fault listing:

```text
python Project1_main.py c432.bench --fault-list
```

3. hw1 circuit simulation, output order w,x,y,z:

```text
python Project1_main.py hw1.bench --vector 011 --trace
python Project1_main.py hw1.bench --vector 101 --trace
```

4. c6288 with every intermediate gate calculation:

```text
python Project1_main.py c6288.bench --vector 0x00050007 --trace
```

5. hw1 named node faults:

```text
python Project1_main.py hw1.bench --vector 011 --fault y-1
python Project1_main.py hw1.bench --vector 011 --fault y-0
```

6. c17 named branch fault:

```text
python Project1_main.py c17.bench --vector 00000 --fault 22-10-0
python Project1_main.py c17.bench --vector 11111 --fault 22-10-0
```

7. hw1, all listed faults with a result for each:

```text
python Project1_main.py hw1.bench --vector 011 --all-faults
python Project1_main.py hw1.bench --vector 101 --all-faults
```

8. c432 prescribed vector and 10 reproducible random vectors:

```text
python Project1_main.py c432.bench --vector 0xABCD1234 --all-faults
python Project1_main.py c432.bench --random 10 --seed 464
```

`--summary-only` hides individual fault rows for `--all-faults`. random batches report counts for each vector independently and cumulative distinct faults.

## inputs and faults

binary strings follow the input declarations, left to right, and must contain exactly one digit per input. for c17 this is node order 1,2,3,6,7.

hex words are zero-padded to the input count. by default, the first input gets the leftmost (most significant) digit. c432 has 36 inputs, so 0xABCD1234 is padded to 0x0ABCD1234. use `--bit-order lsb-first` if the assignment maps the first input to the least significant bit. this setting affects hex words and generated random words; explicit binary strings always follow declaration order. the program prints the chosen mapping and actual binary vector.

`--fault y-1` forces node y to 1. `--fault 22-10-0` forces only the pin from node 10 at gate 22 to 0. named faults work even when omitted by collapsing. numeric IDs refer to the current fault list. if one gate has repeated pins from the same source, use a full-list ID to identify the particular pin.

the default `--fault-model collapsed` preserves the original local gate-collapse policy: 50 entries for hw1, 32 for c17, and 636 for c432. `--fault-model full` retains both polarities at every primary-input stem, gate input pin, gate output, and primary-output pin: 86, 50, and 1078 entries respectively. separate ports and pins are counted separately even when equivalent; these counts are not globally deduplicated equivalence classes. always identify the model when reporting coverage.

```text
python Project1_main.py hw1.bench --fault-list --fault-model full
```

## other options and verification

```text
python Project1_main.py hw1.bench --input a=0 --input b=1 --input c=1
python Project1_main.py hw1.bench --truth-table
python verification/verify_project.py
```

truth tables are limited to 16 inputs. supported gates are AND, NAND, OR, NOR, XOR, NOT, and BUFF. malformed declarations, empty pins, cycles, undefined nodes, missing inputs, and overflowing vectors are rejected.

see [verification report](VERIFICATION_REPORT.md) and [current results](verification/results.json). the validator refreshes the raw program transcripts in `verification/`.

the hand-work section and screenshot pdfs remain separate submission deliverables. the text transcripts are evidence of runs, not screenshot pdfs or handwritten work.
