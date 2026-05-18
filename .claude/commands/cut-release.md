- **Validate published version**: Before any changes, check the currently published version on PyPI (`pip index versions par-textual-image  2>/dev/nul, If the local version matches the published version, the version MUST be bumped before deploying — otherwise the deploy will publish stale code under the existing version number.
- Bump version
- Update CHANGELOG.md, docs/ and README.md
- Run `make precommit`
- Commit and push
- Run `make deploy` to trigger cicd workflow

$ARGUMENTS
