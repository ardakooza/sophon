# Sophon — `set` Parser/Runtime Update

## Implemented

- Added top-level `set name = expression` parsing and execution.
- `set` updates an already-declared state; it never creates a new state.
- Existing state type is preserved. `number` accepts integer or float; other types remain strict.
- Reassigning the same value produces `S246`.
- Unknown target or malformed `set` syntax produces `S284`.
- Type mismatch produces `S289`.
- Datetime built-ins remain read-only and produce `S245`.
- Function `execute` blocks support `set` for parameters and local states declared earlier in the function.
- Function `set` cannot mutate outer/global states. Function-local type constraints are checked at runtime.
- Documentation and tests were updated.

## Examples

```sph
state name = "arda"
set name = "elif"

state age: integer = 18
set age = 19
```

```sph
function {
    id = "increment"
    input { value: integer }
    execute {
        set value = value + 1
        state result = value
        set result = result * 2
    }
    output: integer = result
}

state answer = increment(5)
```

## Verification

- Python compilation: passed.
- Integration tests: 53/53 passed.
- Existing regression tests: 51/51 passed.
- Documentation parser: 55/55 code blocks parsed.
- Error catalog: all 269 documented/implemented code entries consistent.
- Audit corpus: all expected pass/reject cases matched.
- CLI `--help` and `--version`: verified by integration tests.

## Scope note

`decide / when / otherwise`, boolean operators and comparison operators remain design-only. This update implements `set` independently so it is ready for later use inside Control Flow branches.
