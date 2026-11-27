---
name: extract_fields
version: 1
output: {"customer": str|null, "core_features": str|null, "platform": str|null, "scope": str|null}
---
Extract from the IDEA only what is explicitly stated. Use null for anything not stated. JSON only.
