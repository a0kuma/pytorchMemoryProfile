# Highlight Logic Analysis

## Question

Does the highlight logic compare rows with the JSON file **by ID**, or by something else?

## Short Answer

**No — it does not compare by ID.**  
It compares by **memory address** (`addr`), using a raw integer equality check.

---

## How It Works (step by step)

### 1. Loading the JSON file (`main_window.py` — `load_peak_json`)

```python
addrs = set()
for entry in data:
    if isinstance(entry, dict) and "addr" in entry:
        addrs.add(entry["addr"])
self.model.set_highlighted_addrs(addrs)
```

- The JSON file (e.g. `peak_alloc_events.json`) is a list of event objects.
- Each event has an `"addr"` key whose value is an **integer** representing a GPU/CPU memory address (e.g. `133557544550400`).
- All those integers are collected into a Python `set`.
- There is **no concept of an "ID" field** — no sequential number, UUID, or named identifier is involved.

### 2. Applying the highlight (`models.py` — `DictTableModel.data`)

```python
if role == Qt.BackgroundRole:
    if self._highlighted_addrs:
        addr = row.get("addr")
        if addr is not None and addr in self._highlighted_addrs:
            return self._HIGHLIGHT_COLOR  # yellow
    return None
```

- For every table row, the model reads the row's `"addr"` field.
- It checks whether that value exists in the `_highlighted_addrs` set (i.e. `addr in set`).
- If it matches, the row is painted **yellow** (`QColor(255, 255, 0)`).

---

## What the comparison key actually is

| Field used | Type | Example value |
|------------|------|---------------|
| `addr`     | `int` | `133557544550400` |

The match is a direct **integer equality** between:
- the `"addr"` value from each entry in the peak-alloc JSON, and  
- the `"addr"` field of each row loaded from the pickle trace.

### Why not by ID?

The JSON events and pickle trace rows share no ID field. They are linked solely by the memory address of the allocation. Two events refer to the same allocation if and only if they have the same `addr` integer.

---

## Summary

| Criterion | Answer |
|-----------|--------|
| Compared by ID? | **No** |
| Compared by what? | **`addr` (integer memory address)** |
| Match type | Exact integer equality via Python `set` membership test |
| Highlight colour when matched | Yellow (`#FFFF00`) |
| Source files | `main_window.py` (`load_peak_json`) · `models.py` (`DictTableModel.data`) |
