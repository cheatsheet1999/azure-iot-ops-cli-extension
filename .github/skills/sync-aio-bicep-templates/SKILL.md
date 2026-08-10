---
name: sync-aio-bicep-templates
description: Generate and safely integrate updated template.py blueprints from an explicit Azure IoT Operations deployment repository and release branch.
---

# Synchronize AIO Bicep templates

Use this workflow when a teammate asks to generate `template.py` for a new AIO release.

## Required inputs

- Local path to `azure-iot-operations-tests`.
- Explicit release branch, tag, or commit, such as `releases/v1.4.x/2608`.
- AIO release moniker, such as `2608`.
- Explicit CLI version policy when it cannot be derived safely.

Do not require the user to know repository implementation details after these inputs are supplied.

## 1. Preflight

1. Confirm the current repository is `azure-iot-ops-cli-extension`.
2. Normalize a `\\wsl.localhost\Ubuntu\...` source path to `/...` when needed.
3. Confirm the source path is a Git repository and the explicit ref resolves.
4. Confirm these source files exist at that ref:
   - `Deployment/azure-iot-operations-enablement.bicep`
   - `Deployment/azure-iot-operations-instance.bicep`
5. Inspect `git status` in the CLI repository.
6. Do not overwrite existing changes in:
   - `azext_edge/edge/providers/orchestration/template.py`
   - `azext_edge/tests/edge/orchestration/test_template_unit.py`
   - `azext_edge/constants.py`
7. Confirm `az bicep`, Python, and Black are available.

## 2. Export and compile

Use temporary storage and export the requested Git ref without switching or modifying the source worktree. Ignore
untracked or modified source-worktree files.

Compile both templates:

```shell
az bicep build \
  --file <exported-source>/Deployment/azure-iot-operations-enablement.bicep \
  --outfile <temp>/enablement.json

az bicep build \
  --file <exported-source>/Deployment/azure-iot-operations-instance.bicep \
  --outfile <temp>/instance.json
```

Run the repository's existing optimizer in JSON mode from the temporary directory so it does not create output in
the CLI worktree. Do not use its Python-output mode: that legacy path invokes Black as a single executable string and
does not work reliably.

```shell
cd <temp>
<python> <cli-repo>/tools/template_optimizer.py <temp>/enablement.json json
<python> -c \
  "import json, pathlib; pathlib.Path('enablement.py').write_text(repr(json.loads(pathlib.Path('optimized.json').read_text())))"
<python> -m black enablement.py --line-length=120 --target-version=py39

<python> <cli-repo>/tools/template_optimizer.py <temp>/instance.json json
<python> -c \
  "import json, pathlib; pathlib.Path('instance.py').write_text(repr(json.loads(pathlib.Path('optimized.json').read_text())))"
<python> -m black instance.py --line-length=120 --target-version=py39
```

Always remove temporary files at the end.

## 3. Compare before editing

Parse the current blueprint assignments from `template.py` without importing that module:

- `TEMPLATE_BLUEPRINT_ENABLEMENT`
- `TEMPLATE_BLUEPRINT_INSTANCE`

Use Python AST and `ast.literal_eval`; do not import `template.py` and do not use broad regex replacement.

Derive each `commit_id` using the latest commit at the selected ref that changed its top-level Bicep file. Show the
selected source-ref commit as additional context. If imported Bicep changes make that provenance insufficient, ask
for an explicit override rather than guessing.

Separate the report into:

- **Routine release changes**
  - template commit IDs;
  - `metadata._generator`;
  - `variables.VERSIONS`;
  - `variables.TRAINS`.
- **Behavioral changes**
  - every other changed path.

For every behavioral difference, show its template name, full object path, old value, and new value. Include additions
and removals. Pay particular attention to:

- resources such as `certManagerExtension`;
- `variables.defaultAioConfigurationSettings`;
- `configurationSettings`;
- parameters and default values;
- definitions;
- dependencies and conditions;
- API versions and resource properties.

Do not hide behavioral changes behind a summary. The 2607 release demonstrated that version bumps can also introduce
important configuration changes.

Present the report before modifying files. Ask the user to confirm when behavioral changes exist.

## 4. Update after review

After confirmation, replace only the two complete blueprint assignments in `template.py`, preserving unrelated code.
Format generated assignments with Black at line length 120.

Also update:

- `EXTENSION_CONFIGS` in `azext_edge/tests/edge/orchestration/test_template_unit.py` from generated
  `variables.VERSIONS` and `variables.TRAINS`;
- `AIO_RELEASE` in `azext_edge/constants.py` from the supplied release moniker.

Apply this CLI `VERSION` policy:

- `integration`: preserve the current version unless the user supplies one.
- `stable` with a prerelease version: promote to its base version, for example `2.8.0a2` to `2.8.0`.
- `stable` with an already stable version: ask for an explicit version.
- Only perform a next-minor bump when explicitly requested, using semantic version components
  (`2.8.0` to `2.9.0`), never string or float arithmetic.

Print all proposed constant changes before editing.

## 5. Validate

After editing:

1. Reparse `template.py` and assert both embedded dictionaries equal the generated dictionaries.
2. Run:

   ```shell
   python -m pytest -q azext_edge/tests/edge/orchestration/test_template_unit.py
   python -m flake8 \
     azext_edge/edge/providers/orchestration/template.py \
     azext_edge/tests/edge/orchestration/test_template_unit.py \
     azext_edge/constants.py
   git diff --check
   ```

3. Show the final diff summary, detected versions/trains, and behavioral changes.

Never commit, push, publish, switch the CLI branch, trigger a release workflow, or modify files outside the declared
scope.
