# Sophon Random Module — Update Report

Date: 2026-11-10

## Scope

- Control Flow design is narrowed to `resolve / when / otherwise` only.
- `select`, `match`, `switch`, and `route` are explicitly outside the current Control Flow scope.
- Implemented the local standard-library module `random` in the Sophon parser/runtime.

## Random API

```sph
use { random }

state dice = random.integer(1, 6)
state probability = random.float()
state enabled = random.boolean()
state colors = ["red", "green", "blue"]
state selected = random.choice(colors)
```

| Function | Behavior |
|---|---|
| `random.integer(min, max)` | Inclusive integer range; both bounds must be integers and min <= max. |
| `random.float()` | Float in `[0.0, 1.0)`. |
| `random.boolean()` | Random boolean. |
| `random.choice(list)` | Random item from a non-empty list. |

The module must be explicitly imported with `use { random }`. It is a local standard library module and does not require a dedicated XAF capability. Programs that use other protected capabilities, such as `surface`, still need their normal XAF policy.

The implementation uses Python's pseudorandom generator. It is not cryptographically secure and must not be used for passwords, API tokens, or security keys.

## Runtime and parser changes

- Registered `random` as an implemented module and local standard library module.
- Added `random.integer`, `random.float`, `random.boolean`, and `random.choice` expression calls.
- Added list expression evaluation and allowed values (including list-valued states) to be passed to function calls, while arithmetic operators continue to enforce numeric operands.
- Random calls work in top-level states, function bodies/default evaluation, and multi-state values.
- Reserved the `random` namespace against state and multi-state identifiers when imported.
- Added explicit import validation and specific diagnostics for invalid calls and arguments.
- Updated README, SYNTAX reference, docs parser module prelude, Control Flow design, and runnable example files.

## Diagnostics

- `S290`: `random` namespace is reserved.
- `S291`: keyword arguments are not supported by random functions.
- `S292`: `random.integer` requires two integer bounds.
- `S293`: minimum exceeds maximum.
- `S294`: `random.float` / `random.boolean` received arguments.
- `S295`: `random.choice` requires one list.
- `S296`: `random.choice` received an empty list.
- `S297`: unknown random function.

## Verification

- 115 regression and integration tests passed.
- 56 SPH/XAF/SVT documentation code blocks parsed successfully.
- All 277 source diagnostic codes are present in the syntax catalogue.
- Python compilation passed.
- `examples/random.sph` was executed through the Sophon CLI using its companion `random.xaf` policy; all four values were produced and displayed.
- Final ZIP was extracted into a clean directory and the test suite was rerun there.
