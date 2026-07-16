# API reference site (auto-generated)

The full API reference — every public module, class, method, and function,
rendered from the docstrings in the source — is generated automatically by
[pdoc](https://pdoc.dev) and published to **GitHub Pages**.

Once Pages is enabled (see below), the site lives at:

```
https://warped-pinball.github.io/python-library/
```

It rebuilds and redeploys on every push to `main`, so it always reflects the
latest released code. Pull requests build the docs too (to catch breakage)
but do not publish.

## Building the docs locally

```bash
pip install -e ".[docs]"
python scripts/gen_docs.py --output site
# open site/index.html in a browser
```

`scripts/gen_docs.py` walks the `warpedpinball` package and hands pdoc an
explicit module list. This is needed because pdoc's automatic submodule
discovery honours a package's `__all__`, and ours lists the public API names
(`connect`, `Machine`, the exception classes, ...) rather than submodule
names — so a bare `pdoc warpedpinball` would only render the top-level page.
The script picks up new modules automatically, so nothing needs updating when
the package grows.

## What you need to do to enable publishing (one time)

The CI workflow (`.github/workflows/docs.yml`) is already committed. GitHub
Pages just needs to be switched on for the repository and pointed at GitHub
Actions as its source:

1. Go to the repository on GitHub → **Settings** → **Pages**
   (`https://github.com/warped-pinball/python-library/settings/pages`).
2. Under **Build and deployment** → **Source**, choose **GitHub Actions**.
   (Do *not* pick "Deploy from a branch" — this project builds the site in
   CI rather than committing HTML.)
3. That's it. Push to `main` (or re-run the **Docs** workflow from the
   **Actions** tab via **Run workflow**) and the `deploy` job will publish
   the site. The live URL is shown in the workflow run's `deploy` job and
   back on the Settings → Pages screen once the first deploy finishes.

### Notes

- **Permissions.** The workflow already requests the `pages: write` and
  `id-token: write` permissions it needs, so no repository-wide permission
  changes are required. If your organization restricts GitHub Actions or
  Pages, an org owner may need to allow Pages for this repo.
- **First deploy.** Pages is only created after the first successful `deploy`
  run, so the URL may 404 for a minute or two after you enable it.
- **Private repos.** Publishing a Pages site from a private repository
  requires GitHub Enterprise/Team. On a public repo it works on the free
  plan.
- **Custom domain (optional).** To serve the docs from your own domain, set
  it under Settings → Pages → **Custom domain**; nothing in the workflow
  needs to change.
