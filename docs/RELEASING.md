# Releasing csetty-mips

Publishing a stable GitHub Release starts the workflow that builds the package,
attaches the wheel and source archive to GitHub, and uploads the same files to
PyPI. A push or merged pull request does not publish a package.

## Prepare the release

1. Update the version in `pyproject.toml` and `src/csetty_mips/__init__.py`.
   Include the tests and documentation for the changes being released.
2. Open a pull request. Address review comments and wait for CI on the final
   commit before merging.
3. From the merged source, build a wheel and source archive. Install the wheel
   in a fresh virtual environment, check `csetty-mips --version`, and run a
   small program through both the CLI and Python API. Keep these local builds
   separate from the files the release workflow will publish.

See [Development](DEVELOPMENT.md) for the build and test commands.

## Publish

Tag the reviewed commit as `vX.Y.Z`, push that tag, and publish a normal GitHub
Release for it. Use the package version in place of `X.Y.Z`; prereleases do not
trigger publication. Write release notes about changes users will notice.

Do not attach local distribution files. The
[release workflow](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/main/.github/workflows/publish-pypi.yml)
builds them once and supplies `SHA256SUMS`. Its three jobs are:

| Job | Result |
|---|---|
| `build` | Checks the tag/version and main-branch ancestry, then builds and checks the distributions |
| `github-release` | Attaches those files and their checksums to the GitHub Release |
| `pypi` | Publishes the same files using the configured Trusted Publisher |

Wait for all three to succeed. Compare the file hashes reported by PyPI with
`SHA256SUMS` on GitHub, then install the version from PyPI in a fresh environment
and run the smoke example again. If the package needs a correction, publish a
new version rather than replacing release files.

## Update MIPS Studio

The browser bundle is a separate deployment; publishing the Python package
does not update it automatically. Use the published wheel, pin its SHA-256
digest in the browser build, and check the loaded engine version after
deployment. Run an assembly example in the browser, including any behavior
fixed by the release. Keep the previous site bundle available for rollback.

## Publisher settings

The PyPI project `csetty-mips` is configured for these GitHub values:

| Field | Value |
|---|---|
| Owner | `JiaruiUNSW` |
| Repository | `CSEtty-MIPS` |
| Workflow | `publish-pypi.yml` |
| Environment | `pypi` |

The GitHub environment allows only tags matching `v*`. The workflow also checks
for a stable version tag, a matching package version, and a commit in `main`
history. No long-lived PyPI token is needed.

Only the PyPI job can request an OIDC token. It downloads the built artifact by
its immutable ID without checking out repository source. The GitHub upload
job has repository write access but no PyPI identity. Actions are pinned to
commit hashes.

## Update build tools

The full build/check dependency set is pinned with hashes in
[requirements-release.txt](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/main/.github/requirements-release.txt).
To update it, edit
[requirements-release.in](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/main/.github/requirements-release.in),
then run:

```sh
uv pip compile --python-version 3.11 --universal --generate-hashes \
  .github/requirements-release.in -o .github/requirements-release.txt
```

Review the generated diff and let CI test it before merging. Both CI and
publication install with `--force-reinstall --require-hashes --only-binary=:all:`
and build with `--no-isolation`. This keeps package builds on the reviewed
tool versions instead of resolving new ones during a release.

## If publication fails

Check which job failed before retrying. GitHub uploads do not overwrite
existing assets, so compare any files already uploaded with the build artifact
and its checksums first. If the GitHub job completed and only PyPI failed,
retry the failed job rather than rebuilding and uploading everything again.

For a Trusted Publisher error, check the owner, repository, workflow filename,
environment, and allowed tag against the settings above. Do not work around
an identity mismatch by adding a broad API token.
