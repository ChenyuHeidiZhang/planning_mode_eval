# Implementation Plan: Improve JSON Formatting Consistency in Chat Adapter

## Context

The DSPy framework currently uses JSON serialization inconsistently across different modules, which can lead to non-deterministic output formatting across optimization runs. This affects:

- **Cache consistency**: Different JSON formatting produces different cache keys, reducing cache hit rates
- **Optimization reproducibility**: Same random seed may produce different results due to formatting variations
- **Training data consistency**: Fine-tuning datasets may have inconsistent formatting
- **Demo formatting**: In-context learning examples may be formatted differently across runs

The root cause is the mixed use of `json` and `ujson` libraries without explicit formatting parameters (indent, sort_keys, separators), leading to variations in whitespace, key ordering, and encoding.

## Recommended Approach

**Standardize all JSON operations on `ujson` with consistent formatting parameters**, specifically `sort_keys=True` to ensure deterministic key ordering. Create a centralized JSON utilities module that provides a single source of truth for JSON serialization throughout the framework.

**Why this approach:**
- `ujson` is already a project dependency and offers better performance
- Centralized utilities enable framework-wide consistency
- Configurable defaults allow flexibility while maintaining determinism
- `sort_keys=True` is critical for reproducibility - ensures dictionary fields always appear in the same order

## Implementation Steps

### 1. Create Core JSON Utilities Module

**File to create:** `dspy/utils/json_utils.py`

This module will provide:
- `dumps_json(obj, **kwargs)` - Serialize to JSON string with consistent defaults
- `dump_json(obj, fp, **kwargs)` - Serialize to file
- `loads_json(s, **kwargs)` - Parse JSON string
- `load_json(fp, **kwargs)` - Parse JSON file
- `JSONConfig` dataclass for configuration

**Key features:**
- Default parameters: `sort_keys=True`, `indent=None`, `ensure_ascii=False`, `escape_forward_slashes=False`
- Configuration inheritance from `dspy.settings.json_config`
- Support for Pydantic model serialization with `model_dump_json_kwargs`
- Thread-safe configuration handling

**Rationale for defaults:**
- `sort_keys=True` - **Most critical** - ensures consistent key ordering across runs
- `indent=None` - Compact format reduces token usage and costs
- `ensure_ascii=False` - Better for international characters
- `escape_forward_slashes=False` - Cleaner URLs in JSON

### 2. Add JSON Configuration to Settings

**File to modify:** `dsp/utils/settings.py` (around line 30-45)

Add to the config dictionary:
```python
json_config=dotdict(
    indent=None,
    sort_keys=True,
    ensure_ascii=False,
    escape_forward_slashes=False,
)
```

This enables:
- Global configuration: `dspy.settings.configure(json_config={'indent': 2})`
- Context-specific overrides: `with dspy.settings.context(json_config={...}):`

### 3. Update ChatAdapter for Consistent Parsing

**File to modify:** `dspy/adapters/chat_adapter.py`

**Changes:**
1. Import: Add `from dspy.utils.json_utils import loads_json, dumps_json`
2. Update `parse_value()` function (line 89):
   - Replace `json.loads(value)` with `loads_json(value)`
   - Maintains fallback chain: JSON → ast.literal_eval → raw value
3. In `format_fields()` (line 76-82):
   - For dict/list fields, serialize with `dumps_json()` to ensure consistency

**Why:** This is the core function that parses LM outputs during optimization. Consistent parsing ensures reproducible field extraction.

### 4. Update TypedPredictor JSON Handling

**File to modify:** `dspy/functional/functional.py`

**Changes:**
1. Import: Add `from dspy.utils.json_utils import dumps_json, loads_json`
2. Update schema generation (lines 240, 245):
   - Replace `json.dumps(type_.model_json_schema())` with `dumps_json(type_.model_json_schema())`
   - Replace `json.dumps(adapter.json_schema())` with `dumps_json(adapter.json_schema())`
3. Update format lambdas (lines 238, 268, 271, 274):
   - Replace `json.dumps(x)` with `dumps_json(x)`
   - For Pydantic models, use `model_dump_json(sort_keys=True)` or wrap in `dumps_json()`
4. Update `_unwrap_json()` function (line 416):
   - Replace `ujson.dumps(ujson.loads(output))` with `dumps_json(loads_json(output))`

**Why:** TypedPredictor is used extensively in optimization. Consistent schema and format strings ensure reproducible prompts.

### 5. Update LM Client Request Serialization

**File to modify:** `dspy/clients/lm.py`

**Changes:**
1. Import: Add `from dspy.utils.json_utils import dumps_json`
2. Update request serialization (line 48):
   - Replace `ujson.dumps(dict(model=self.model, messages=messages, **kwargs))` with `dumps_json(dict(...))`

**Why:** This ensures consistent cache keys for LiteLLM requests. Same parameters will always produce the same serialized request, improving cache hit rates.

### 6. Update Fine-tuning Data Generation

**File to modify:** `dspy/teleprompt/finetune.py`

**Changes:**
1. Import: Add `from dspy.utils.json_utils import dumps_json`
2. Update training data writing (line 128):
   - Replace `ujson.dumps(line)` with `dumps_json(line)`

**Why:** Ensures consistent training data format across optimization runs. Critical for reproducible fine-tuning results.

### 7. Update State Serialization

**File to modify:** `dspy/predict/predict.py`

**Changes:**
1. Update `dump_state()` method (line 44):
   - Add `sort_keys=True` parameter to `model_dump_json()` calls
   - Ensures consistent checkpoint serialization

**Why:** Model checkpoints and demo serialization must be deterministic for reproducible optimization.

### 8. Add Comprehensive Tests

**New test file:** `tests/utils/test_json_utils.py`

**Test cases:**
- Verify `sort_keys=True` produces deterministic output
- Test configuration inheritance from settings
- Test Pydantic model handling
- Test edge cases (unicode, nested structures, numbers)
- **Critical consistency test:** Same data serialized 1000 times produces identical strings

**Integration tests:** Add to existing test files
- Test ChatAdapter parsing consistency
- Test TypedPredictor schema generation
- Test LM client cache key consistency
- Run optimization multiple times and verify identical results with same seed

## Critical Files

1. **`dspy/utils/json_utils.py`** (NEW) - Foundation module with consistent JSON utilities
2. **`dspy/adapters/chat_adapter.py`** - Core adapter, `parse_value()` function (lines 85-93)
3. **`dspy/functional/functional.py`** - TypedPredictor formatting (lines 238-278, line 416)
4. **`dspy/clients/lm.py`** - Request serialization (line 48) for cache consistency
5. **`dsp/utils/settings.py`** - Global configuration (lines 28-47)

## Verification Strategy

### End-to-End Test
Run the same optimization multiple times with the same random seed:

```python
import dspy
from dspy import Example

# Configure with deterministic settings
dspy.settings.configure(lm=dspy.LM(model="gpt-3.5-turbo", temperature=0.0))

# Run optimization 10 times
results = []
for i in range(10):
    predictor = dspy.Predict("question -> answer")
    predictor.demos = [Example(question="What is 2+2?", answer="4").with_inputs("question")]

    # Serialize the predictor state
    state = predictor.dump_state()
    results.append(ujson.dumps(state, sort_keys=True))

# Verify all serializations are identical
assert len(set(results)) == 1, "Inconsistent serialization across runs"
```

### Cache Hit Rate Test
Run the same LM call multiple times and verify cache hits:

```python
lm = dspy.LM(model="gpt-3.5-turbo", cache=True)
dspy.settings.configure(lm=lm)

# Make same call 10 times
for i in range(10):
    result = lm(prompt="Test prompt")

# Check that 9 out of 10 were cache hits (first is cache miss)
assert lm.history[-1]["cost"] is None, "Should be cache hit"
```

### Training Data Consistency Test
Generate training data twice and verify identical output:

```python
# Generate training data twice
data1 = generate_training_data(examples, optimizer)
data2 = generate_training_data(examples, optimizer)

# Read generated files and compare byte-by-byte
with open("train1.jsonl", "rb") as f1, open("train2.jsonl", "rb") as f2:
    assert f1.read() == f2.read(), "Training data differs across runs"
```

## Backward Compatibility

**Maintained:**
- Existing cached data remains readable (parsing is unchanged)
- Existing checkpoints load correctly
- All existing tests pass
- Parse fallback chain preserved (JSON → ast.literal_eval → raw)

**Potential issues:**
- Cache keys may change (different serialization), causing cache misses temporarily
- Optimization results may differ slightly if previous runs had inconsistent formatting

**Mitigation:**
- Add migration notes to CHANGELOG
- Consider cache versioning to handle format changes
- Provide flag to use legacy JSON formatting if needed: `dspy.settings.configure(legacy_json=True)`

## Success Criteria

1. ✅ Same data produces identical JSON string across 1000+ serialization runs
2. ✅ All existing tests pass without modification
3. ✅ Cache hit rates improve or remain stable
4. ✅ Optimization runs with same seed produce identical prompts and demos
5. ✅ Training data generation is deterministic
6. ✅ No performance regression in JSON operations
7. ✅ 90%+ test coverage for json_utils module

## Implementation Order

1. Create `json_utils.py` with comprehensive unit tests
2. Update `settings.py` to add JSON configuration
3. Update `chat_adapter.py` for consistent parsing
4. Update `functional.py` for TypedPredictor
5. Update `lm.py` for client serialization
6. Update `predict.py` for state serialization
7. Update `finetune.py` for training data
8. Add integration tests
9. Run full regression test suite
10. Update documentation and CHANGELOG

**Estimated effort:** 2-3 days implementation, 1-2 days testing and validation
