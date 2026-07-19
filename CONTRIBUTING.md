# Contributing

Use a feature branch and keep lifecycle changes narrowly scoped. Never write tests that enumerate,
attach, rename, or delete arbitrary sessions from a developer's live tmux server.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
make check
```

Pull requests should include tests for behavior changes and explain ownership or migration effects.
Commits must not contain pane captures, session notes, local project names, credentials, or private
paths. Run `make secret-scan` before pushing.

By participating, contributors agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

