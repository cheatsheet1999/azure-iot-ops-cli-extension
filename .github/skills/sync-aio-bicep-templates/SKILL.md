---
name: sync-aio-bicep-templates
description: Generate and safely integrate updated template.py blueprints from the azure-iot-operations-tests deployment repository and an explicit release ref.
---

# Synchronize AIO Bicep templates

Use this workflow when a teammate asks to generate `template.py` for a new AIO release.

## Required inputs

- Local path to the `azure-iot-operations-tests` deployment repository.
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
   - `Deployment/release.json`
   - `AioExtension/helm/aio/values.yaml`
5. Inspect `git status` in the CLI repository.
6. Do not overwrite existing changes in:
   - `azext_edge/edge/providers/orchestration/template.py`
   - `azext_edge/tests/edge/orchestration/test_template_unit.py`
   - `azext_edge/constants.py`
7. Confirm `az bicep`, Python, and Black are available.
8. Parse `Deployment/release.json` from the selected ref and confirm its `release` value equals the supplied release
   moniker. Fail on a mismatch rather than combining metadata from different releases.

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

JSON mode still runs the optimizer's JSON serialization round-trip assertions. The conversion to Python is covered
by section 5, which reparses the final assignments and requires exact dictionary equality with the optimized JSON.

Always remove temporary files at the end.

## 3. Compare before editing

Parse the current blueprint assignments from `template.py` without importing that module:

- `TEMPLATE_BLUEPRINT_ENABLEMENT`
- `TEMPLATE_BLUEPRINT_INSTANCE`

Use Python AST and `ast.literal_eval`; do not import `template.py` and do not use broad regex replacement.

Determine provenance explicitly for each template:

1. Enumerate all transitively referenced local source files, including Bicep imports, local modules, and files read
   by `loadJsonContent`, `loadYamlContent`, or `loadTextContent`.
2. Derive the latest commit at the selected ref that changed the top-level Bicep file.
3. Compare every referenced file at that top-level commit with the same file at the selected ref. Treat a missing
   file as a difference.
4. If no referenced file differs, use the top-level Bicep commit as `commit_id`.
5. If any referenced file differs, report the files and commits that changed and ask for an explicit `commit_id`
   override rather than guessing.

Show the selected source-ref commit as additional context.

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
- `stable` with an already stable version: ask for an explicit version because the AIO release moniker does not
  establish whether the CLI version should remain unchanged or advance.
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

## 6. Generate the IoT Operations versions wiki payload

After all template edits and validation succeed, print a ready-to-paste Markdown update for the
[IoT Operations versions wiki](https://github.com/Azure/azure-iot-ops-cli-extension/wiki/IoT-Operations-versions).
Do not edit or push the wiki.

Print both:

1. the new row for the appropriate **Version Matrix by AIO Release** table;
2. the complete detailed release section.

### Collect release values

Use the validated post-update embedded templates for release-facing AIO and dependency extension values:

- AIO version:
  `TEMPLATE_BLUEPRINT_INSTANCE.content.variables.VERSIONS.iotOperations`;
- AIO train:
  `TEMPLATE_BLUEPRINT_INSTANCE.content.variables.TRAINS.iotOperations`;
- Cert Manager version/train:
  `TEMPLATE_BLUEPRINT_ENABLEMENT.content.variables.VERSIONS.certManager` and
  `TEMPLATE_BLUEPRINT_ENABLEMENT.content.variables.TRAINS.certManager`;
- Key Vault Secret Store version/train:
  `TEMPLATE_BLUEPRINT_ENABLEMENT.content.variables.VERSIONS.secretStore` and
  `TEMPLATE_BLUEPRINT_ENABLEMENT.content.variables.TRAINS.secretStore`;
- compatible CLI version: final `VERSION` in `azext_edge/constants.py`.

Cross-check embedded template values against the generated ARM dictionaries. If a final embedded value intentionally
differs from the generated upstream value because of release policy, keep the final embedded value in the wiki
payload and prominently report the discrepancy.

Read core component versions from `AioExtension/helm/aio/values.yaml` exported from the same selected ref:

| Wiki component | YAML path |
| --- | --- |
| Mqtt Broker | `mqttBroker.image.tag` |
| Data Flows | `dataFlows.image.tag` |
| Connectors | `connectors.image.tag` |
| Akri | `akri.image.tag` |
| Schema Registry | `schemaRegistry.image.tag` |
| Device Registry | `adr.image.tag` |
| AIO Observability | `aioObservabilityOperator.image.tag` |

Parse YAML structurally with `yaml.safe_load`; do not select version-like strings with broad grep. Require every path
to resolve to a non-empty scalar. Use `yaml.compose` node marks, or another path-aware YAML parser, to obtain the exact
source line for each value.

Derive the AIO series from the semantic AIO version, for example `1.4.41` becomes `1.4.x`. Do not use the release
moniker to infer the product version.

Construct these proposed public links:

- AIO release:
  `https://github.com/Azure/azure-iot-operations/releases/tag/v<AIO_VERSION>`;
- CLI release:
  `https://github.com/Azure/azure-iot-ops-cli-extension/releases/tag/v<CLI_VERSION>`.

The links may not exist yet during release preparation; label them as proposed in the surrounding report.

### Manual placeholders

Do not guess information that is not authoritative in the selected templates or release metadata. Use these exact,
visible placeholders:

- `<RELEASE_DATE>`;
- `<UPGRADE_FROM_AIO>`;
- `<CLI_RELEASE_DATE>`.

### Print the version-matrix row

Print:

```markdown
| [<RELEASE_MONIKER>](#<RELEASE_MONIKER>) | <RELEASE_DATE> | <AIO_VERSION> | <UPGRADE_FROM_AIO> | <CLI_VERSION> |
```

Also state which existing series table (`AIO <major>.<minor>.x Series`) should receive the row.

### Print the detailed release section

Match the wiki's existing format:

```markdown
### [<RELEASE_MONIKER>](https://github.com/Azure/azure-iot-operations/releases/tag/v<AIO_VERSION>)

**AIO Version:** <AIO_VERSION> **|** **Release Date:** <RELEASE_DATE> **|** **Release Train:** <AIO_TRAIN>

⏫ **Upgrade From (AIO):** <UPGRADE_FROM_AIO>

**Core Components**
| Component | Version |
|-----------|---------|
| Mqtt Broker | <MQTT_BROKER_VERSION> |
| Data Flows | <DATA_FLOWS_VERSION> |
| Connectors | <CONNECTORS_VERSION> |
| Akri | <AKRI_VERSION> |
| Schema Registry | <SCHEMA_REGISTRY_VERSION> |
| Device Registry | <DEVICE_REGISTRY_VERSION> |
| AIO Observability | <AIO_OBSERVABILITY_VERSION> |

**Dependency Extensions**
| Extension | Version | Train |
|-----------|---------|-------|
| Cert Manager | <CERT_MANAGER_VERSION> | <CERT_MANAGER_TRAIN> |
| Key Vault Secret Store | <SECRET_STORE_VERSION> | <SECRET_STORE_TRAIN> |

**Compatible CLI Versions**
| CLI Version | Release Date | Notes |
|-------------|--------------|-------|
| <CLI_VERSION> | <CLI_RELEASE_DATE> | [Release](https://github.com/Azure/azure-iot-ops-cli-extension/releases/tag/v<CLI_VERSION>) |
```

### Print source provenance

After the paste-ready Markdown, print a separate **Source provenance** table. This table is for review and does not
need to be pasted into the wiki.

Include one row for every populated field:

```markdown
| Field | Value | Source |
|-------|-------|--------|
| AIO version | 1.4.41 | `releases/v1.4.x/2607:Deployment/azure-iot-operations-instance.bicep:89`; compiled path `variables.VERSIONS.iotOperations`; final `azext_edge/edge/providers/orchestration/template.py:<line>` |
```

Source requirements:

- identify the selected ref and resolved commit;
- calculate line numbers from files exported from that ref, not the current source worktree;
- cite `Deployment/release.json:<line>` for the release moniker;
- cite the source Bicep declaration line, compiled JSON object path, and final `template.py:<line>` for AIO and
  dependency extension values;
- cite `AioExtension/helm/aio/values.yaml:<line>` for each core component;
- cite `azext_edge/constants.py:<line>` for the CLI version;
- use Python AST node positions to locate final Python values instead of broad text matching;
- fail if a source path is absent, duplicated ambiguously, or cannot be tied to an exact line.

When generated upstream and final embedded values differ, add a **Release-policy overrides** section showing:

- field;
- upstream value and source;
- final embedded value and source;
- the user-approved policy decision.

Never commit, push, publish, switch the CLI branch, trigger a release workflow, or modify files outside the declared
scope.
