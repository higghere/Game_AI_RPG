# Genesis Rule Language (GRL) Specification

**Version:** 3.1  
**Phase:** Phase 0 / Phase 1  
**Status:** Approved with Engineering Conditions  

---

## 1. Design Philosophy

The Genesis Rule Language (GRL) is a strictly bounded, domain-specific declarative rule representation designed specifically for autonomous rule generation by an LLM within a sandboxed simulation.

### Phase 1 Scope Decision
- **Parser & Validator:** In Phase 1, the runtime implements a **JSON AST parser and schema validator only**. A standalone DSL compiler is omitted in favor of pure, unambiguous structured AST verification.
- **Read-Only Formatter:** A read-only human-readable serializer converts JSON AST rules into clean formatted text for logging, debugging, and review.

---

## 2. Mandatory Limits and Quota Semantics

The runtime strictly enforces the following quotas:

```yaml
grl:
  max_operations_per_rule: 256
  max_loop_depth: 4
  recursion_allowed: false
  max_entities_touched_per_tick: 1000
```

### 2.1 Operation Accounting
An **Operation** is defined as one evaluated GRL node:
- Property read / write
- Relationship lookup / edge mutation
- Resource query / transfer / consume / produce
- Comparison operator evaluation (`==`, `!=`, `<`, `<=`, `>`, `>=`)
- Branch evaluation (`if` condition)
- Loop construct step + each statement executed per iteration

> **Enforcement:** If `operations_count > 256`, the rule halts immediately with `QuotaExceededError("max_operations_per_rule exceeded: 256")`.

### 2.2 Entities Touched Quota
- Tracked as the set of unique `EntityID` values inspected or mutated during rule evaluation.
- **Reads count toward the quota.** Filtering across entities consumes touch quota to prevent free whole-world scanning.
- If $|\mathcal{S}_{\text{touched}}| > 1000$, execution halts immediately with `QuotaExceededError("max_entities_touched_per_tick exceeded: 1000")`.

### 2.3 Rollback Scope & Deterministic Rule Ordering
- Rules in the registry are sorted deterministically before evaluation:
  $$\text{Sort Order} = (\text{priority} \downarrow, \text{rule\_id} \uparrow)$$
- **Rollback Scope:** Violation of an operational quota ($\le 256$ operations, $\le 1000$ touched entities) rolls back **only the single offending rule**. Preceding and succeeding rules maintain their deterministic execution path.

### 2.4 Multi-Target Precondition & Selection Semantics
To prevent unnecessary whole-world entity touches and eliminate ambiguity in multi-target rules:
1. **Rule Preconditions (`rule.preconditions`):** Evaluated **once globally** before any candidate entities are fetched or inspected. These express macro-environmental gates (e.g. `world.resource("sunlight") >= 1.0`). If any global precondition evaluates to `false`, the rule terminates immediately with **zero entities touched**, conserving operational budget.
2. **Target Selector Filter (`target_selector.filter`):** Evaluated **per candidate entity** with `target` bound to that candidate. Only candidate entities satisfying this filter are queued for effect application.
3. **Effects Execution (`rule.effects`):** Evaluated sequentially for each matched target candidate. Per-entity conditional branches within effects are expressed via `IF` nodes.

---

## 3. Data Types and JSON String Encoding Guard

To prevent silent IEEE-754 precision loss beyond $2^{53}$ in JSON parsers, all 64-bit numerical values in GRL AST and state snapshots are encoded as decimal strings:

| GRL Type | Canonical JSON Representation | Constraints |
| :--- | :--- | :--- |
| `INT64` | Stringified integer, e.g. `"9223372036854775807"` | Signed 64-bit integer range |
| `FIXED_POINT` | Stringified scaled integer, e.g. `"1500000"` (scale $10^6$) | Precision $0.000001$, `half_even` rounding |
| `BOOLEAN` | Boolean literal `true` or `false` | Strict boolean |
| `STRING` | String literal, e.g. `"active"` | Max 256 UTF-8 bytes, no path characters |
| `ENTITY_REF` | Stringified uint64, e.g. `"42"` | Refers to an existing entity ID |
| `ENUM` | String literal matching enum variant | Constrained to registered variant set |

---

## 4. GRL JSON AST Schema

Every GRL rule is represented by a JSON object matching this formal structure:

```json
{
  "rule_id": "rule_hydration_uptake_v1",
  "name": "Plant Hydration Uptake",
  "version": "1.0.0",
  "priority": 100,
  "target_selector": {
    "entity_type": "organism",
    "filter": {
      "op": "EQUALS",
      "left": {
        "op": "GET_PROPERTY",
        "entity": "target",
        "property": "is_alive"
      },
      "right": {
        "op": "LITERAL",
        "type": "BOOLEAN",
        "value": true
      }
    },
    "limit": 50
  },
  "preconditions": [
    {
      "op": "GREATER_THAN_OR_EQUAL",
      "left": {
        "op": "GET_RESOURCE",
        "pool": "soil_moisture"
      },
      "right": {
        "op": "LITERAL",
        "type": "FIXED_POINT",
        "value": "5000000"
      }
    }
  ],
  "effects": [
    {
      "op": "CONSUME_RESOURCE",
      "pool": "soil_moisture",
      "amount": {
        "op": "LITERAL",
        "type": "FIXED_POINT",
        "value": "5000000"
      }
    },
    {
      "op": "ADJUST_PROPERTY",
      "entity": "target",
      "property": "hydration",
      "delta": {
        "op": "LITERAL",
        "type": "FIXED_POINT",
        "value": "5000000"
      }
    }
  ]
}
```

---

## 5. Read-Only Human-Readable Serializer

The runtime includes a serializer that renders GRL ASTs into cleanly formatted pseudocode for terminal logging and human review:

```text
RULE rule_hydration_uptake_v1 [v1.0.0, Priority: 100]
TARGET organism IN world.entities("organism") LIMIT 50
  WHERE target.is_alive == true
PRECONDITIONS:
  world.resource("soil_moisture") >= 5.000000
EFFECTS:
  CONSUME_RESOURCE soil_moisture AMOUNT 5.000000
  ADJUST_PROPERTY target.hydration BY +5.000000
```
