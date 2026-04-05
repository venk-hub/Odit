# Support

## In-App Help

The fastest way to get help is the built-in documentation at **http://localhost:8000/help** once Odit is running. It covers every screen, tab, and button with screenshots.

## Documentation

- [Installation guide](docs/installation.md) — requirements, Docker setup, environment variables
- [Usage guide](docs/usage.md) — running audits, reading results, AI features, exports
- [Full docs site](https://venk-hub.github.io/Odit/) — complete help page on GitHub Pages

## Reporting Bugs

Open a [GitHub Issue](https://github.com/venk-hub/Odit/issues) with:
- What you expected to happen
- What actually happened
- Your OS and Docker Desktop version
- Relevant logs (`docker compose logs -f worker` or `docker compose logs -f app`)

## Common Issues

**Audit stuck on "running"**
```bash
docker compose restart worker
```

**No vendors detected**
- Check that mitmproxy is running: `docker compose logs proxy`
- Make sure the proxy container started before the worker

**App won't start**
```bash
docker compose down -v
docker compose up --build
```

**AI features not working**
- Go to **Settings** in the app and verify your Anthropic API key is saved
- Check `docker compose logs app` for API errors

## Feature Requests

Open a [GitHub Issue](https://github.com/venk-hub/Odit/issues) with the label `enhancement`. Describe your use case and why existing features don't cover it.
