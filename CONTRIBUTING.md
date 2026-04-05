# Contributing to Odit

Thank you for your interest in contributing! Here's how to get involved.

## Ways to Contribute

- **Bug reports** — open an issue with steps to reproduce, expected vs actual behaviour, and your OS/Docker version
- **Feature requests** — open an issue describing the use case and why existing features don't cover it
- **Pull requests** — fix a bug, add a vendor signature, improve the UI, or extend the rule engine

## Development Setup

```bash
git clone https://github.com/venk-hub/Odit.git
cd Odit
cp .env.example .env
docker compose up --build
```

See [docs/installation.md](docs/installation.md) for full setup instructions.

## Adding Vendor Signatures

The easiest contribution — no code required. Edit `worker/detectors/vendors.yaml`:

```yaml
vendors:
  - key: my_vendor
    name: My Vendor
    category: analytics   # analytics|tag_manager|ab_testing|consent|pixel|other
    signatures:
      domains: [cdn.myvendor.com]
      script_patterns: [myvendor.js]
      window_globals: [window.myVendor]
      cookie_patterns: [_mv_]
```

## Adding Issue Detection Rules

Add a function to `worker/rules/rule_engine.py` and register it in `ALL_RULES`:

```python
def rule_my_check(audit_run, pages, requests, events, vendors, config):
    issues = []
    # ... logic ...
    return issues
```

## Pull Request Guidelines

- Keep PRs focused — one bug fix or feature per PR
- Test your change with a real audit (`pytest tests/ -v` for unit tests)
- Update `README.md` if you're adding a user-facing feature
- Follow the existing code style — no linters configured, just match the surrounding code

## Running Tests

```bash
pip install pytest openpyxl pyyaml
pytest tests/ -v
```

## Licence

By contributing, you agree your contributions will be licensed under the [AGPL-3.0](LICENSE).
