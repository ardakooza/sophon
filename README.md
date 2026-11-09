<p align="center">
  <img src="assets/1794262869564.png" alt="Sophon" width="760" />
</p>

<h1 align="center">Sophon</h1>

<p align="center"><strong>A policy-controlled programming language and runtime</strong></p>

<p align="center">Write a program. Define its permissions. Run it with Sophon.</p>

---

Sophon runs `.sph` programs. Each program connects to an `.xaf` file that describes its policy and component settings. Persistent records live in `.svt` Sophon Vault files. The language combines state, expressions, user interaction, terminal components, file and database operations, observation, and Agent requests.

This README is an in-depth guide to the language as implemented in this repository. It explains the file formats, syntax, runtime behavior, modules, permissions, and practical limits. For the exhaustive syntax catalogue and every diagnostic code, see [SYNTAX.md](SYNTAX.md). For the complete XAF v2 schema, see [XAF_V2_SCHEMA.md](XAF_V2_SCHEMA.md).

## Contents

- [Quick start](#quick-start)
- [The three file types](#the-three-file-types)
- [Writing Sophon source](#writing-sophon-source)
- [Values, types, and expressions](#values-types-and-expressions)
- [Imports and standard library](#imports-and-standard-library)
- [Runtime order and state](#runtime-order-and-state)
- [Core statements](#core-statements)
- [Functions](#functions)
- [Terminal components and forms](#terminal-components-and-forms)
- [Sophon Vault](#sophon-vault)
- [Files and subprograms](#files-and-subprograms)
- [Observers](#observers)
- [Agents](#agents)
- [XAF configuration and policy](#xaf-configuration-and-policy)
- [CLI and development checks](#cli-and-development-checks)
- [Current implementation limits](#current-implementation-limits)
- [Reference documents](#reference-documents)

## Quick start

The repository includes a launcher and needs Python 3. No package installation is required:

```bash
git clone https://github.com/ardakooza/sophon.git
cd sophon
./sophon --version
./sophon --help
```

Create `hello.sph`:

```sph
connect to hello.xaf
use { random }

state name = "Sophon"
state greeting = "Hello, {name}!"
state roll = random.integer(1, 6)
state result = "Dice result: {roll}"

surface {
    greeting
    result
}
```

Run the program from its project directory:

```bash
./sophon run hello.sph
```

A program must connect to an XAF file even when it only uses local language features. If `hello.xaf` does not exist, Sophon can create a minimal file when the program starts. Inspect generated policies before using them in a real project. Existing XAF content is preserved; Sophon fills missing schema defaults rather than replacing the file.

The roll is random, so its value changes between runs. The program first defines `name`, builds `greeting` and `result` from earlier states, then sends those state values to `surface` for display.

## The three file types

| Extension | Name | Purpose |
|---|---|---|
| `.sph` | Sophon program | Source code parsed and run by Sophon. |
| `.xaf` | Sophon policy/configuration | Capabilities, actions, resource boundaries, and shared component settings. It is not run directly. |
| `.svt` | Sophon Vault | Local structured records accessed through the `database` module. |

A `.sph` file selects its XAF with one `connect` statement:

```sph
connect to app.xaf
```

The target must end in `.xaf` and use a relative path accepted by Sophon. A source file can have only one `connect`. Without it, execution stops with `X008`. `create` and `create xaf` can create and connect to the default policy file; they can be chained with `connect to ...` using `&` on the same line.

Automatic policy creation is based on the `.sph` file name. If several programs share an XAF, add their policies to that file yourself; Sophon does not automatically create a second program policy inside an existing XAF.

## Writing Sophon source

A `.sph` program is a sequence of top-level statements and blocks. Blocks use braces. Put each top-level statement on its own line. Some nested blocks accept compact one-line forms; use the examples for each statement rather than assuming arbitrary blocks can be flattened.

State and field names start with a letter or underscore and continue with letters, digits, or underscores; they cannot contain a dot. A dotted reference such as `person.name` means “the `name` field in the `person` group”; it is not a declaration name. Module names allow hyphens, as in `multi-observer`. XAF v2 Agent, Policy, and Observer IDs are positive integers.

`//` starts a line comment in `.sph`, `.xaf`, and `.svt` files:

```sph
// A full-line comment
state count = 3 // A trailing comment
```

Blank lines are allowed. Comments are not accepted in every block: raw-scanned bodies such as `surface`, `ask`, `choice`, and terminal component bodies treat their contents as values, so keep comments outside those blocks. The full reference calls out each exception.

A useful mental model is:

- The source file names the features a program wants to use.
- `use` explicitly imports non-core modules and component types.
- `connect` selects the policy/configuration file.
- The runtime checks configured capabilities and actions before protected operations.
- Results are held in states, displayed by `surface` or components, or written to a Vault/file when the XAF allows it.

Block bodies are parsed by statement-specific readers. Avoid putting comments inside `surface`, `ask`, `choice`, or terminal component bodies; those readers treat their contents as values and settings rather than general source text. Comments inside a `confirmation` block are accepted, but comments inside its nested `choice` block are not.

## Values, types, and expressions

Sophon values include:

| Value type | Examples |
|---|---|
| Integer | `17`, `-3` |
| Float | `3.5`, `-0.5`, `2.` |
| String | `"Ada"`, `"Hello"` |
| Boolean | `true`, `false` |
| Null | `null` |
| List | `[1 2 3]`, `["red", "blue"]`, `[]` |
| Object | A function's named multi-value result or structured runtime value |

Strings require double quotes. The supported escapes include `\"` and `\\`. In a Sophon list, commas are optional: `[a b]` and `[a, b]` have the same meaning. An unquoted word in a list is literal text, not a reference to a state. Empty lists are valid; every item in a non-empty list must contain a value.

Declare a state with an inferred type:

```sph
state name = "Ada"
state age = 31
state active = true
```

Or declare the type explicitly:

```sph
state name: string = "Ada"
state age: integer = 31
state ratio: float = 0.75
state score: number = 12
state tags: list = ["math" "science"]
```

Supported declared types are `string`, `integer`, `float`, `number`, `boolean`, `list`, `object`, and `null`. `number` accepts either an integer or a float; `integer` and `float` remain distinct types. An explicit type must match its value. A state can refer to states declared earlier in the source.

Sophon supports numeric `+`, `-`, `*`, `/`, `^`, parentheses, and `sqrt(expression)`. These are arithmetic operators; `+` is not string concatenation. Build text with interpolation inside a state:

```sph
state first = "Ada"
state greeting = "Hello, {first}"
surface { greeting }
```

Interpolation happens when a string is assigned to a state. A quoted string written directly as a `surface` item does not interpolate at runtime. Prepare the string in a state, then display that state. The parser has a few legacy operand contexts that may still accept literal concatenation with `+`; do not rely on that transitional behavior.

Division by zero and malformed numeric expressions produce diagnostics. Logical operators and comparisons are not implemented in this runtime; see [Current implementation limits](#current-implementation-limits).

## Imports and standard library

`use` is required for modules and component types. Core statements do not require it.

```sph
use { database observer agent }
use { component }
use { list from component }
use { list from component file }
```

The `from` form imports a specific component type from the `component` module. A module must be imported before use. Empty imports, duplicate imports, unknown modules, and attempts to import reserved future modules are rejected.

| Module | Features | XAF requirements |
|---|---|---|
| `datetime` | Local date/time values and fields | No module capability; the program still needs `connect`. |
| `random` | Integer, float, boolean, and list-choice values | No module capability; the program still needs `connect`. |
| `database` | `.svt` Vault operations | `access.database` and the matching action permission. |
| `observer` | Observe one current or external `.sph` source | Observer profile, `access.observer`, source permission, and read action. |
| `multi-observer` | Group several observer definitions | Multi feature configuration and policy permission, plus observer permissions. |
| `component` | Group terminal boxes in a `component` block | `access.component` for a grouped component. |
| `file` | Read and change project files and directories | File-system capability, allowed paths, detailed file/folder actions, and global action. |
| `execute` | Run an allow-listed `.sph` subprogram | `access.execute` and a matching `config.execute.file` entry. |
| `agent` | Send a message or task to a configured Agent | Agent record, connection settings, `access.agent`, read action, and `permission.execute`. |

`datetime` and `random` are local standard-library modules and do not need an XAF capability grant. All `.sph` files still need an XAF connection. `math`, `system`/`sys`, and `multi-agent` are reserved for future work and are not importable in this release. `function` is part of the core language and does not need `use`.

### `datetime`

Import `datetime` to access the local date/time snapshot:

```sph
use { datetime }
state today = date
state clock = time
state day = date.day
state month = date.month
state year = date.year
state weekday = date.weekday
state timezone = date.timezone
state hour = time.hour
state minute = time.minute
state second = time.second
```

`date` and `time` are strings formatted as `YYYY-MM-DD` and `HH:MM:SS`. Their fields expose numeric day, month, year, ISO weekday (Monday is 1), hour, minute, and second values; `date.timezone` is the local IANA zone when available, otherwise the system abbreviation or offset. These values are captured from one local instant while the program is parsed. The names `date` and `time` are reserved when `datetime` is imported.

### `random`

```sph
use { random }
state die = random.integer(1, 6)
state probability = random.float()
state enabled = random.boolean()
state color = random.choice(["red" "green" "blue"])
```

| Function | Result |
|---|---|
| `random.integer(min, max)` | Integer in the inclusive range. Both arguments must be integers and `min` must not exceed `max`. |
| `random.float()` | Float in `[0.0, 1.0)`. Takes no arguments. |
| `random.boolean()` | Boolean. Takes no arguments. |
| `random.choice(list)` | One item from a non-empty list. |

The `random` namespace is reserved when imported. The generator is not cryptographically secure and must not be used for passwords, API tokens, or security keys.

## Runtime order and state

Sophon parses the source and resolves its program declarations before applying runtime effects. Top-level runtime operations run in this order:

1. Agent calls.
2. Database operations.
3. File operations.
4. Subprogram or command execution.
5. User prompts (`ask`, `multi-ask`, and confirmations).
6. Terminal output (`surface` and component boxes).
7. Observers.

Within the prompt stage, prompts keep their source order. Within the display stage, `surface` blocks and boxes keep their source order. At top level, all prompts run before any display, regardless of where those statements appear in the source. This allows a top-level `surface` to refer to a value supplied by a later `ask` statement.

Forms are different: their steps run one at a time in source order. Put an `ask` before a `surface` that displays its answer. The `file`, `execute`, and `database` stages run before prompts, so prompts can display state produced by those operations.

`state` creates a named value. Reassigning an existing state to a different compatible value preserves its original type; assigning the same value again is an error. `set name = value` makes an update explicit, never creates a missing state, and must preserve the type. A redundant same-value update is rejected.

`multi-state` stores named fields under one group ID. The first declaration must contain at least two fields. Later declarations can update existing fields but cannot add new ones. Access a field with `group.field`. Optional `at [N]` positions reorder fields using one-based positions within the existing group.

```sph
multi-state {
    id = "person"
    state {
        name = "Ada"
        age = 31
    }
}

multi-state {
    id = "person"
    state {
        age = 32
    }
}

state label = "{person.name} is {person.age}"
```

An update may also move an existing field. Positions start at 1 and cannot exceed the current number of fields. For example, `age = 32 at [2]` updates the value and moves that field to position 2; `age at [3]` moves it without changing the value.

Multi features (`multi-state`, `multi-ask`, `multi-confirmation`, and `multi-observer`) require both the feature name in `config.multi` and `multi` in the applicable policy's `access` block.

The same multi-feature gate applies to the `multi-state` form used as an `ask` or `confirmation` target. Declare the group in `config.multi` even when it is created by user input.

## Core statements

These statements are part of the language rather than separately imported modules:

| Statement | Purpose |
|---|---|
| `connect` | Selects the XAF file for this program. |
| `state` | Declares a single value, optionally with an explicit type. |
| `set` | Updates an existing state without changing its type. |
| `multi-state` | Declares or updates a group of named fields. |
| `surface` | Writes states and values to standard output. |
| `ask` | Prompts for one value or a grouped set of values. |
| `multi-ask` | Runs a named sequence of prompts. |
| `confirmation` | Prompts the user to choose from fixed options. |
| `multi-confirmation` | Runs a named sequence of confirmations. |
| `function` | Declares a typed function with local scope and output. |

`surface` needs at least one item. A state reference is printed with its name and value; a list can be printed as one value. Secret input is masked. `surface` output and form content go to `stdout`; errors and stand-alone prompts go to `stderr`, so shell redirection can capture program output without capturing prompts.

### `ask`

An `ask` requires an `id`, a `prompt`, and exactly one target: `state` or `multi-state`.

```sph
ask {
    id = "nickname"
    prompt = "What should I call you?"
    state = nickname
    type = "text"
    default = "guest"
    suggestion = "for example, Ada"
    requirement = true
    duration = 15
    secret = false
}
```

| Setting | Required | Meaning |
|---|---:|---|
| `id` | Yes | Diagnostic label; it is not the target state name. |
| `prompt` | Yes | Text shown to the user. |
| `state` | One target required | Unquoted target state name. |
| `multi-state` | One target required | Collects fields in a grouped state. |
| `type` | No | `"text"` by default, or `"number"`. Invalid numeric input is prompted again. |
| `default` | No | Literal value used for an empty answer or timeout; it cannot refer to a state. |
| `suggestion` | No | Hint shown with the prompt; it does not validate input. |
| `requirement` | No | `true` rejects an empty response; `false` allows skipping. |
| `duration` | No | Positive timeout in seconds. |
| `secret` | No | Masks the response and excludes it from observer snapshots/logs. |

When `requirement = false`, an empty answer without a default stores `null`. If `requirement = true` and a duration is set, a default is required. Without a duration, a required empty answer is requested again. End-of-file on standard input produces an error instead of hanging.

A single `ask` can collect multiple fields:

```sph
ask {
    id = "profile"
    multi-state {
        name { prompt = "Name:" }
        password { prompt = "Password:" secret = true }
        age { prompt = "Age:" type = "number" default = 18 }
    }
}
```

Each field needs a prompt and field names must be unique.

### `multi-ask`

`multi-ask` contains one or more sibling `ask` blocks and has a group `id`. Questions run one at a time in source order. A nested `ask` inside another `ask` is not supported.

```sph
multi-ask {
    id = "address"
    ask { id = "city" prompt = "City:" state = city }
    ask { id = "country" prompt = "Country:" state = country }
}
```

In a form, the `multi-ask` ID is rendered as a section heading.

### `confirmation` and `multi-confirmation`

A `confirmation` requires an ID, prompt, non-empty `choice` block, and exactly one destination: `state` or a two-field `multi-state` target.

```sph
confirmation {
    id = "terms"
    prompt = "Do you accept the terms?"
    choice {
        yes = true
        no = false
    }
    state = accepted
    requirement = true
    default = "no"
}
```

Choices have a label and a constant value, such as `yes = true`, or a quoted value whose label and value are the same, such as `"blue"`. The user can answer with the label or its displayed option number. Choice values must be constants, not state references. Labels must be unique. A `default` selects a choice label or value for an empty response or end-of-file. If `requirement = false`, an empty response skips the confirmation and stores `null`.

For the two-field target, the first field receives the selected value and the second receives the label the user selected. Both field names are declared in the nested `multi-state` block.

Set `multiple-selection = true` to store a list of selected choice values. Multi-selection requires `requirement = true`; `min-selection` defaults to 1 and `max-selection` defaults to the number of choices. The minimum cannot exceed the maximum, and the maximum cannot exceed the number of available choices. A multi-selection cannot use the `multi-state` target.

`multi-confirmation` contains one or more confirmation blocks and has a group ID. As with `multi-ask`, each contained confirmation is a sibling entry, not a nested chain of groups.

```sph
multi-confirmation {
    id = "preferences"
    confirmation {
        id = "email"
        prompt = "Send email updates?"
        choice { yes = true no = false }
        state = email_updates
    }
    confirmation {
        id = "sms"
        prompt = "Send text updates?"
        choice { yes = true no = false }
        state = sms_updates
    }
}
```

## Functions

A function has a unique quoted `id`, typed inputs, an `execute` body, and an output declaration. It must be declared before it is called.

```sph
function {
    id = "calculate"
    input {
        value: integer
        multiplier: integer = 2
        label: string?
    }
    execute {
        state result = value * multiplier
    }
    output: integer = result
}

state answer = calculate(21)
```

Inputs can be required, have a default, or be optional with `?`. Calls accept positional or named arguments; a parameter cannot be supplied both ways or more than once. Supported parameter types are `string`, `integer`, `float`, `number`, `boolean`, `list`, `object`, and `null`. `number` accepts integer or float values.

Functions can return one typed state or an object containing several named states:

```sph
function {
    id = "statistics"
    input { left: integer right: integer }
    execute {
        state sum = left + right
        state difference = left - right
    }
    output { sum difference }
}

state result = statistics(9, 4)
state total = result.sum
```

Function-local states do not escape the call. A function can read the outer states already available at its call site, but cannot mutate them. `set` inside a function can update parameters or local states declared earlier in that function. Calls can nest; recursion is limited to 32 levels.

Function expressions are currently evaluated while the program's states are parsed. They cannot consume values produced later by `ask`, an Agent call, or another runtime-only operation. This is an implementation boundary, not a limitation of the function declaration syntax.

## Terminal components and forms

Import `component` to group boxes, or import a specific box type with `from component`. `component` is a container, not a box type. Available boxes are `note`, `list`, `table`, and `form`. Import all box types with `use { component }`, or import individual types with `use { form from component }`, `use { note from component }`, `use { list from component }`, and `use { table from component }`.

```sph
use { component }

component {
    id = "overview"
    note { title = "Status" text = "Ready" }
    list { title = "Features" item = "Policy" item = "Vault" }
    table { title = "Profile" row "name" "Ada" row "age" 31 }
}
```

A component group may contain boxes in source order and may have its own optional ID. Boxes can also be imported and declared directly. A box can have an `id`, `title`, and `width`. The title is displayed in its frame; the ID is used as the title if no title is given. Width defaults to 60 columns and must be at least 10.

- `note` is read-only text and needs at least one `text` line.
- `list` displays one or more `item` entries.
- `table` displays one or more `row` entries. Each row is made from column operands.
- `form` runs interactive steps in the order written. Its supported steps are `surface`, `ask`, `confirmation`, `multi-ask`, and `multi-confirmation`.

A form's prompts are written to `stdout` so the whole form can be captured as output. A secret response is never echoed; the form displays a mask instead. Put a `surface` after the `ask` that creates the state it displays. Empty component bodies and empty forms are rejected. Component body parsers scan raw text, so do not place comments inside their contents.

```sph
use { form from component }

form {
    id = "signup"
    title = "Create an account"
    ask { id = "name" prompt = "Name:" state = name }
    surface { name }
    confirmation {
        id = "updates"
        prompt = "Receive updates?"
        choice { yes = true no = false }
        state = updates
    }
}
```

## Sophon Vault

A `.svt` file starts with `vault {` and contains `record` blocks. Each record requires a unique `id`; field values use Sophon literal types. Strings inside Vault lists must be quoted.

```svt
vault {
    record {
        id = 1
        name = "Ada"
        age = 31
        tags = ["math" "science"]
    }
    record {
        id = 2
        name = "Grace"
        age = 29
    }
}
```

Use a `database` block to read or change records:

```sph
use { database }

state selected_user = null

database users {
    connect = data/users.svt
    read { id = 1 state = selected_user }
    write { id = 3 name = "Lin" age = 28 }
    modify { id = 3 age = 29 }
    remove { id = 2 }
}
```

The database block name (`users` above) is an alias. Its `connect` value must point to a `.svt` file inside the project. The operations are `read`, `write`, `modify`, and `remove`, requiring the matching global `action.read`, `action.write`, `action.modify`, or `action.remove` respectively. A write needs an ID and cannot reuse an existing ID; changes that match an ambiguous record are rejected. Records without IDs cannot be reliably updated or deleted and are not accepted.

XAF can set `config.database.connection.provider = "local"`, `max-records`, and `max-bytes`. Database use needs `policy.access.database` and the corresponding `policy.action` permission. Vault paths are resolved within the project root, and changes are saved atomically so a failed replacement leaves the previous file intact.

## Files and subprograms

Import `file` before using file operations. Every path must be relative to the project and remain inside it, including after symbolic links are resolved. XAF must explicitly allow the paths and operations. `forbidden_path` entries take precedence over `allowed_path` entries.

```sph
use { file }

state report = "Sophon is ready."
file {
    mkdir { path = "output" }
    create { path = "output/report.txt" }
    write { path = "output/report.txt" data = report }
    append { path = "output/report.txt" data = " More text." }
    read { path = "output/report.txt" state = saved_report }
    list { path = "output" state = files }
    copy { path = "output/report.txt" to = "output/backup.txt" }
    move { path = "output/backup.txt" to = "output/archive.txt" }
    zip { path = "output" to = "output.zip" }
    unzip { path = "output.zip" to = "unpacked" }
    delete { path = "unpacked" }
}
```

Available operations are `create`, `write`, `append`, `read`, `list`, `delete`, `copy`, `move`, `mkdir`, `zip`, and `unzip`. Paths and destinations are quoted. `read` and `list` write their result into a named state. `copy`, `move`, `zip`, and `unzip` require a `to` destination. String interpolation for file data should be prepared in a state.

File access is checked against all of the following: `policy.access.file-system`, `config.file-system.allowed_path` and `forbidden_path`, the file/folder operation list in `config.file-system.action`, and the matching global `policy.action`. For example, `write` needs `action.write` plus the file `modify` operation. Paths that leave the project are rejected. `unzip` rejects entries that would escape its destination.

The detailed file/folder operation requirements are:

| SPH operation | `config.file-system.action` | Global `policy.action` |
|---|---|---|
| `create` | `file { create }` | `create` |
| `write`, `append` | `file { modify }` | `write` |
| `read` | `file { read }` | `read` |
| `list` | `folder { read }` | `read` |
| `delete` | `file { delete }` or `folder { delete }` for the target | `remove` |
| `copy`, `move` | `file { copy }` or `file { move }`, for both source and destination | `modify` |
| `mkdir` | `folder { create }` | `create` |
| `zip`, `unzip` | `folder { zip-unzip }` | `modify` |

The XAF also needs a non-empty `allowed_path`; a path can never be used if it matches `forbidden_path`, even if another allowed entry covers it.

The `execute` module can run a different `.sph` file with its own XAF policy:

```sph
use { execute }
execute { file = "worker.sph" }
```

The target must be allowed under `config.execute.file`, and `policy.access.execute` must be granted. Subprogram nesting is limited to four levels to prevent cycles. The `command` form is parsed but the Sophon command registry is currently empty; shell commands are not executed.

## Observers

An `observer` watches one current or external `.sph` source. Its `watch` block can select a single state, a full `multi-state` group, one field such as `person.age`, or the whole source file when the `self-observation` feature is enabled.

```sph
use { observer }
state status = "ready"

observer {
    id = 1001
    description = "Watch program status"
    source = self
    watch {
        status
    }
}
```

Use `source = self` for the current source or `source = "other.sph"` for an external source. A `multi-observer` groups several observer definitions and is imported separately with `use { multi-observer }`.

```sph
use { multi-observer }
multi-observer {
    id = "project-watch"
    observer {
        id = 1001
        source = self
        watch { status }
    }
    observer {
        id = 1002
        source = "worker.sph"
        watch { result }
    }
}
```

Every observer needs a unique numeric ID, a source, and at least one watch target. The ID must have a matching `config.observer` profile in the relevant XAF. That profile controls whether watching and JSON logging are enabled, the log path and detail level, and which changes are recorded. `policy.access.observer`, `policy.access.source` (`self` and/or `external`), and `policy.action.read` are also checked. Multi-observer additionally needs the multi capability and feature configuration.

For example, the SPH observer with ID `1001` can use this XAF profile and policy:

```xaf
config {
    observer {
        1001 {
            watch = true
            log = true
            path = "logs"
            level = detailed
            action {
                read = true
                modify = true
                create = true
                remove = false
                reorder = false
            }
        }
    }
}

policy {
    id = 2001
    access {
        observer
        source { self = true external = false }
    }
    action { read = true }
}
```

The profile ID must match the SPH ID. With `log = true`, `path` is required and must remain inside the project. With `log = false`, no JSON log is written; Sophon still updates its internal snapshot to calculate future changes. The log level can be `compact`, `normal`, `detailed`, or `debug`.

The `self-observation` feature is enabled in a root-level XAF block:

```xaf
features {
    self-observation = true
}
```

It is distinct from a normal observer profile. Secret `ask` values are removed before snapshots and logs are written. Observer details and log levels are in [XAF_V2_SCHEMA.md](XAF_V2_SCHEMA.md).

The feature must be enabled in the XAF connected to the source being observed. If it is active for the running file, a separate observer with `source = self` is rejected because the complete source is already covered by self-observation.

## Agents

The `agent` module connects an `.sph` program to an Agent record in XAF. The source declares which Agent it will use:

```sph
use { agent }
agent connect { id = 1001 }
```

A program can then issue a message or a task. `agent run` accepts exactly one of `message` or `task`; its optional `output` setting names the state that receives the reply. `agent task` is the task-only form.

```sph
state reply = ""
agent run {
    id = 1001
    message { "Summarize the current project." }
    output = reply
}
surface { reply }
```

An Agent request can also attach project files:

```sph
agent run {
    id = 1001
    message { "Review these files." }
    input {
        file = "image.png"
        file = "notes.txt"
    }
}
```

Attachment paths are resolved relative to the `.sph` file and must remain inside the project. Each attachment is checked against `input.max-bytes` (per file), `policy.access.file-system`, `config.file-system`, and `policy.action.read`. PNG, JPG/JPEG, GIF, and WebP files are sent as image data; other files must be UTF-8 text. An empty `input` block is invalid. The `input.max-token` estimate covers text, not image token usage.

An Agent record has a positive numeric ID, a name, and either a reference to a policy ID or an inline policy. `config.agent` contains shared defaults; an Agent may override them. The key settings are:

| Setting | Purpose |
|---|---|
| `permission.execute` | Must be `true` for the Agent request to run. |
| `security.container` | Requests the Linux Agent provider-call sandbox. |
| `timing.delay` | Timeout for each provider request. |
| `timing.timeout` | Total deadline, including retries and retry delays. |
| `timing.retry.duration`, `timing.retry.count` | Delay between retries and number of additional attempts. |
| `input.max-token` | Approximate input text token limit. It is not an exact model tokenizer count. |
| `input.max-bytes` | Maximum byte size for each attached input file. |
| `output.max-token` | Provider output token limit. |
| `connection.provider`, `connection.model` | Provider and model identifiers. OpenRouter is the implemented provider. |
| `connection.key` | Name of the environment variable holding the API key, not the key itself. |

Here is a complete Agent configuration shape. Put the real key in the named environment variable; XAF stores only its name.

```xaf
config {
    default-policy = 2001
    agent {
        permission { execute = true }
        security { container = false }
        timing {
            delay = 60
            timeout = 180
            retry { duration = 2 count = 3 }
        }
        input { max-token = 12000 max-bytes = 5242880 }
        output { max-token = 4096 }
        connection {
            provider = "openrouter"
            model = "provider/model-id"
            key = "OPENROUTER_API_KEY"
        }
    }
}

agent {
    id = 1001
    name = "Research Agent"
    policy = 2001
}

policy {
    id = 2001
    access { agent }
    action { read = true }
}
```

The source may send a task instead of a message. `agent run` accepts exactly one of `message` and `task`; `agent task` accepts only a task:

```sph
agent task {
    id = 1001
    task { "Review the source and summarize its behavior." }
}
```

An Agent call requires `policy.access.agent`, `policy.action.read`, `permission.execute = true`, and valid connection settings. The program uses the first connected Agent for CLI message/task mode. Calls can make network requests and may incur provider charges. Keep credentials in environment variables, never in XAF or source files.

Agent calls also require an `AGENT.md` operating specification in the project or runtime directory. Sophon loads it as the Agent's runtime instructions; if it is missing, the call fails with `A026`. It defines the Agent's task/message behavior, policy boundaries, resource meanings, and treatment of untrusted file or tool input.

When `security.container = true`, the runtime attempts Linux user, mount, PID, UTS, IPC, and network namespace isolation plus `chroot`, a read-only project mount, resource limits, and a proxy limited to `openrouter.ai:443`. This sandbox wraps the provider request process; it is not a general-purpose sandbox for running generated code or tools. If the host lacks the required namespace features, Sophon fails closed with `A035`. Android and Termux support depends on the host's Linux capabilities. See [SANDBOX.md](SANDBOX.md) for details.

## XAF configuration and policy

XAF v2 is the current policy format. A root `config` block defines shared limits and defaults; root `agent` blocks define Agent records; root `policy` blocks define permissions; root `features` enables optional runtime features.

The main `config` sections are:

| Section | Controls |
|---|---|
| `multi` | Which of `multi-state`, `multi-ask`, `multi-confirmation`, and `multi-observer` may be used. |
| `observer` | Numeric observer profiles: watch/log switches, log path, detail level, and event filters. |
| `database` | Local Vault provider and record/file size limits. |
| `file-system` | Allowed and forbidden project paths and file/folder operations. |
| `execute` | Allow-list of `.sph` subprograms; the command registry is empty. |
| `agent` | Shared permission, security, timing, input, output, and connection defaults. |

A policy separates resource capabilities (`access`) from global actions (`action`). A capability does not automatically grant every operation on that resource. The applicable settings are combined: for example, a file write needs the file-system capability, an allowed path, detailed file `modify` permission, and global `action.write = true`.

A minimal policy for an Agent-free program can use `default-policy` and the read action:

```xaf
config {
    default-policy = 1001
}

policy {
    id = 1001
    action { read = true }
}
```

A policy with protected capabilities can be more specific:

```xaf
config {
    default-policy = 2001
    multi { multi-state multi-ask multi-confirmation multi-observer }
    file-system {
        allowed_path { "data" "output" "output.zip" "unpacked" }
        forbidden_path { "data/private" }
        action {
            file { create read modify copy move delete }
            folder { create read modify copy move delete zip-unzip }
        }
    }
    execute {
        file { "worker.sph" }
        command { }
    }
}

policy {
    id = 2001
    access { multi database file-system execute observer component }
    action {
        read = true
        write = true
        modify = true
        create = true
        remove = true
        reorder = false
    }
}
```

XAF v2 supports these `policy.access` capabilities: `multi`, `observer`, `database`, `file-system`, `execute`, `agent`, and `component`. Observer policies can also include `source { self = true external = false }`; each source permission is independent and defaults to false. `state`, `surface`, `ask`, and their ordinary single-value forms are not access capabilities in v2. The v2 runtime allows ordinary `surface`, `ask`, and input primitives without a dedicated `access` grant. `access.input` is not a valid v2 permission.

The global `action` keys are `read`, `write`, `modify`, `remove`, `create`, and `reorder`. Missing or false actions are denied. Agent execution needs `access.agent`, `action.read`, and the Agent's `permission.execute`. Observer operation needs its capability, a matching profile, an allowed source, and read permission.

| Action | Typical meaning |
|---|---|
| `read` | Read data or allow an operation classified as a read. |
| `write` | Write new file or record content. |
| `modify` | Change existing content; detailed file rules may classify a write as file `modify`. |
| `remove` | Delete a file, folder, or record. |
| `create` | Create a file, folder, or record. |
| `reorder` | Change item or field order where supported. |

Policies can inherit from one another. Use `inherits = 2000` for ordinary inheritance. To revoke inherited access, put `deny` inside an `inherits` block. A deny remains effective through descendant policies even when a lower policy grants the same capability or action. Cyclic or missing policy references are rejected.

Agent and policy IDs are positive integers in XAF v2. Older name-based records and legacy observer profiles are read for compatibility, but new files should use the current numeric-ID schema. The exact XAF fields and constraints are documented in [XAF_V2_SCHEMA.md](XAF_V2_SCHEMA.md).

When no Agent is connected, `config.default-policy` selects the policy for the program. When Agents are connected, their Agent policies govern the connected program's protected operations and their calls. An inline policy may be used instead of a policy ID, but both forms cannot be supplied on the same Agent record.

## Diagnostics

Sophon errors include a short code, message, source file, line, and often a hint. The leading letter identifies the area:

| Prefix | Area |
|---|---|
| `S` | SPH syntax, types, statements, and modules |
| `X` | XAF parsing, policy, permission, and configuration |
| `F` | File and project-path operations |
| `V` | Sophon Vault parsing and data operations |
| `O` | Observer source, permissions, or logs |
| `A` | Agent configuration, invocation, or provider request |
| `W` | Recoverable warning, such as a damaged observer log |

For exact codes and causes, use the [diagnostic catalogue in SYNTAX.md](SYNTAX.md#hata-ve-uyarı-kataloğu). Fix the first reported parse or policy error before investigating later runtime errors.

## CLI and development checks

```bash
./sophon --help
./sophon --version
./sophon run program.sph
./sophon agent -f program.sph -m "Hello."
./sophon agent -f program.sph -t "Complete this task."
```

`run` requires one `.sph` file. Agent CLI modes require `-f` and exactly one of `-m` or `-t`; there is no default program. Both use the first Agent connected by that source. Help and version options are available without running a program.

The repository includes these optional checks:

```bash
python3 test_regressions.py
python3 -m unittest -v test_language_integration.py
python3 check_docs.py
python3 run_audit_corpus.py
```

`run_audit_corpus.py` creates its cases in a temporary directory and removes that directory when it exits.

## Current implementation limits

The following items are not implemented language features in this runtime:

- Conditional control flow. The planned `resolve / when / otherwise` syntax is design-only. `if`, `else`, boolean operators, and comparison operators cannot be used for branching.
- Multi-Agent teams, delegation, and parallel Agent execution. `multi-agent` is planned, not importable.
- `math`, `system`, and `sys` modules.
- `execute { command = ... }`. The registry of trusted Sophon commands is currently empty; shell execution is not provided.
- General-purpose code/tool isolation. The optional Linux sandbox applies to the Agent provider request process only.

Other practical boundaries are deliberate: string concatenation with `+` is not part of the language, `random` is not cryptographic, function calls cannot consume later runtime values, and XAF permissions default to denied when absent.

## Reference documents

| Document | Use it for |
|---|---|
| [SYNTAX.md](SYNTAX.md) | Full SPH syntax, statement settings, value rules, CLI details, and diagnostic catalogue. |
| [XAF_V2_SCHEMA.md](XAF_V2_SCHEMA.md) | Every XAF v2 field, permission, policy inheritance rule, and validation constraint. |
| [SANDBOX.md](SANDBOX.md) | Agent sandbox design, Linux requirements, network boundary, and limitations. |
| [FUNCTIONS_DESIGN.md](FUNCTIONS_DESIGN.md) | Function parameters, local scope, returns, and call rules. |
| [CONTROL_FLOW_DESIGN.md](CONTROL_FLOW_DESIGN.md) | Proposed control-flow syntax; not implemented in the parser/runtime. |
| [SPH_XAF_COMPLETE_REFERENCE.md](SPH_XAF_COMPLETE_REFERENCE.md) | Combined SPH/XAF reference; treat design-only sections as proposals. |
| [audit_suite/README.md](audit_suite/README.md) | Small source programs and policy/data cases used by the audit corpus. |

## Project status

Sophon is under active development. For current parser behavior, use this README together with [SYNTAX.md](SYNTAX.md) and the implementation in [sophon.py](sophon.py). For current policy validation, use [XAF_V2_SCHEMA.md](XAF_V2_SCHEMA.md). Design documents describe planned work and should not be read as evidence that a feature is already available.
