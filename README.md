# ECE464Project1
Proj1 with Ethan, Mo, and Leo

## Parse and evaluate a BENCH circuit

Run the circuit parser to see the nodes in dependency order:

```text
python Project1_main.py hw1.bench
```

Evaluate one input assignment by providing a `--input NAME=BIT` option for
every `INPUT` in the file:

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
