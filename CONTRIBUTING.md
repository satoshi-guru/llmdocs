# Contributing

Thanks for your interest in llmdocs! Issues and pull requests are welcome.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

Please keep changes focused, add a test for any behavior change, and make sure
`pytest -q` is green before opening a PR.

## Security / leak gate — maintainers please read

CI runs two leak-prevention steps (see `.github/workflows/ci.yml`):

1. **Fork-safe structural scan** — generic patterns (absolute home paths, common
   API-key/secret shapes). Safe to commit publicly, so it runs on **every** PR,
   including forks.
2. **Private denylist scan** — the project owner's specific private infra/identity
   strings, held in the `LEAK_DENYLIST` repo secret. GitHub does **not** expose repo
   secrets to workflows triggered by **fork** pull requests, so this step is
   **skipped** on fork PRs.

> ⚠️ **Do not merge a fork PR on a green check alone.** A skipped step still reports
> success, so the private-denylist scan does *not* protect against a fork PR. Before
> merging any PR from a fork, either re-run CI from a same-repo branch (which has the
> secret) or manually review the diff for private strings. The post-merge `push` run
> to `main` scans with the secret, but that is *after* the change is already in
> history — too late for a public repo.
