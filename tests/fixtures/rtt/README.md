# RTT fixtures

- `spec_*.json`: written by hand from the OpenAPI spec (`docs/rtt-openapi.yml`), reproducing the quirks of one real
  board response captured by another open project (`docs/rtt-api.md`, "Observed quirks"). They are **not recordings**.
  Each has a `_note` saying so.
- `real_*.json`: recordings made with `realliferail record` against `data.rtt.io`. None yet, because there was no token
  when this was built. When some exist, `tests/test_parse.py` parses every one of them, and `tests/test_schema.py`
  validates them against the spec.

Recording costs allowance. One board plus two trains is 3 calls, plus 1 or 2 to check the token. Tokens never appear in
response bodies, so recordings can be committed as they are.
