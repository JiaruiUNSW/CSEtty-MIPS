# Releasing csetty-mips

1. Update the version, documentation and regression tests in a pull request.
   Wait for CI and review of its final commit, then merge it into `main`.
2. Tag the merged commit `vX.Y.Z` and publish a non-prerelease GitHub Release.
   Do not attach locally rebuilt distributions: the release workflow builds
   the wheel and source archive once, checks their metadata, and uploads both
   with `SHA256SUMS` to that release.
3. The same workflow publishes those exact files to PyPI. Wait for all three
   jobs in **Publish release** to succeed, then compare the PyPI file digests
   with the GitHub release checksums. Do not overwrite an existing release
   asset or reuse a published version to correct a packaging error.
4. Downstream browser bundles should use that wheel and pin its SHA-256 digest.
   Check the runtime version and an assembly/run smoke test after deployment.

## Trusted Publisher configuration

PyPI project `csetty-mips` trusts GitHub owner `JiaruiUNSW`, repository
`CSEtty-MIPS`, workflow `publish-pypi.yml`, and environment `pypi`.
Configure that GitHub environment to allow only tags matching `v*`.
The workflow additionally rejects non-stable version tags, version mismatches,
and commits outside `main` history. It does not run on pull requests or pushes.

Only the PyPI job can request an OIDC token; it downloads the already-built
artifact by immutable artifact ID and does not check out or execute repository
source. GitHub release asset upload runs in a separate job with repository
write access but no PyPI identity. All Actions are pinned to commit hashes.
No long-lived PyPI token or repository secret is required.

If a job fails, inspect its logs before retrying. Release uploads deliberately
do not overwrite existing assets, so a partially uploaded release requires
checking the existing files and their digests before any manual recovery.
