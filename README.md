# ECE464Project1
Proj1 with Ethan, Mo, and Leo

## Parse and evaluate a BENCH circuit

Run the circuit parser to see the nodes in dependency order:

```text
python Project1_main.py hw1.bench
```

Run without input options to be prompted for a test vector. Enter one bit per
input in the order printed by the program. For `c17.bench`, whose input order
is `1, 2, 3, 6, 7`, entering `10101` assigns those five values in that order.

You can also provide an input combination using a `--input NAME=BIT` option
for every `INPUT` in the file:

```text
python Project1_main.py hw1.bench --input a=0 --input b=1 --input c=0
```

For small circuits, print the output for every possible input combination:

```text
python Project1_main.py hw1.bench --truth-table
```

Truth-table generation is limited to circuits with at most 16 inputs to avoid
exponentially large output. Supported gate types are `AND`, `NAND`, `OR`,
`NOR`, `XOR`, `NOT`, and `BUFF`.

Print the gate-pin stuck-at fault list with basic equivalence and dominance
collapsing:

```text
python Project1_main.py c17.bench --fault-list
```

For an AND gate, the collapsed list retains stuck-at-1 faults at each input
pin and a stuck-at-0 fault at the output. NAND, OR, and NOR use the
corresponding polarity. NOT and BUFF retain both output faults because their
input and output faults are equivalent. XOR faults are retained at every
input and output pin. Faults are listed per gate pin, so separate fanout pins
remain distinct.
