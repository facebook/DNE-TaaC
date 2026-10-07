---
description: Driver Compatibility Checker for restarting and validating the FBOSS Agent across Classic OS, NetOS nspawn, and NetOS native devices; exercising TAAC FBOSS driver methods; diagnosing config-reload, Bitsflow, COOP, SSH, and health-check behavior; and producing correctly classified compatibility reports. Use this skill whenever a user asks to restart wedge_agent or the FBOSS Agent on a lab switch, verify Agent/BGP recovery, compare TAAC behavior across FBOSS OS variants, run the driver tester, or interpret its failures.
---

# Driver Compatibility Checker

Use this project together with the TAAC Copilot skill. TAAC Copilot supplies the
framework conventions; this skill supplies the project-specific commands,
validation contract, and result classification.

## Project location

All project-specific source and tests live here:

```text
fbcode/neteng/test_infra/dne/taac/utils/driver_compatibility_checker/
```

Keep one canonical implementation in this shared TAAC utility package. Do not
duplicate checker implementations under individual user script directories.

## Lab access

Use the lab-ssh MCP tools for every direct device command. Never invoke
`ssh`, `sush`, `scp`, or `sftp` from a shell. Add the exact hostname pattern to
`~/.config/lab-ssh/hosts.conf` when authorization is required.

Driver commands must set `TAAC_SSH_VIA_LAB_SSH=1`; the project binaries do this
through the established TAAC driver path.

## Restart the Agent on demand

Prefer the OS-aware compatibility checker. It asks the driver to identify the
OS type, resolves the correct service and transport, restarts the Agent, waits
for Agent CONFIGURED, and optionally waits for BGP convergence.

```bash
buck2 run fbcode//neteng/test_infra/dne/taac/utils/driver_compatibility_checker:netos_compatibility_checker -- \
  --device <hostname>
```

Skip only the BGP convergence check when the request is explicitly Agent-only:

```bash
buck2 run fbcode//neteng/test_infra/dne/taac/utils/driver_compatibility_checker:netos_compatibility_checker -- \
  --device <hostname> \
  --skip-bgp-check
```

Repeat `--device` to validate multiple devices. The checker intentionally runs
them sequentially to avoid simultaneous control-plane disruption.

Do not hardcode a raw `systemctl` command in automation. Use
`FbossSystemctlServiceName.AGENT` and let the FBOSS driver map Classic OS,
NetOS nspawn, and NetOS native service/transport differences.

## Required restart validation

A submitted restart command is not success. Confirm all of the following:

1. The checker reports the detected OS type.
2. `fboss2 show version` is reachable through the driver.
3. The Agent restart completes without a transport error.
4. Agent reaches CONFIGURED before the timeout.
5. BGP converges unless `--skip-bgp-check` was intentionally selected.
6. Report each device independently; absorb one device's exception and continue
   checking the remaining devices.

## Run focused driver checks

Config reload:

```bash
buck2 run fbcode//neteng/test_infra/dne/taac/utils/driver_compatibility_checker:driver_tester -- \
  --device <hostname> \
  --interface <interface> \
  --only async_agent_config_reload \
  --output-dir <absolute-output-directory> \
  --fail-on-error
```

Reload-dependent patchers:

```bash
buck2 run fbcode//neteng/test_infra/dne/taac/utils/driver_compatibility_checker:driver_tester -- \
  --device <hostname> \
  --interface <interface> \
  --only async_register_patcher_to_shut_ports_persistently \
  --only async_unregister_patcher_to_shut_ports_persistently \
  --only async_isolate_test_bed_connectivity \
  --only async_restore_test_bed_connectivity \
  --only async_add_static_route_patcher \
  --output-dir <absolute-output-directory> \
  --fail-on-error
```

Cross-OS health-check paths:

```bash
buck2 run fbcode//neteng/test_infra/dne/taac/utils/driver_compatibility_checker:netos_healthcheck_compatibility_checker -- \
  --device <hostname>
```

## Diagnose config-reload failures

When Agent reload or patcher application fails:

1. Run `fboss2 create config` through lab-ssh and preserve the exact error.
2. Check the generated and active Agent configs for incompatible port profiles.
3. Check the active `bitsflow_lockdown_level` and COOP's desired Bitsflow state.
4. After a config rollout, rerun `fboss2 create config`, direct reload, and the
   reload-dependent patcher set.
5. Verify the selected test interface and all critical services recovered.

Do not attribute a reload failure to user credentials until configuration
generation and Bitsflow state have been ruled out.

## Classify report results

Use these product-verdict categories:

| Result | Meaning |
|---|---|
| `PASS` | The method or equivalent underlying operation was validated successfully |
| `FAIL` | A reproducible genuine FBOSS product failure |
| `N/A` | The run cannot produce a product verdict: unsupported platform/API, invalid test input, patcher defect, infrastructure failure, timeout, or missing precondition |

Patcher defects are `N/A` product-test results with **P1 follow-up**. They are
not genuine product failures. Keep their method names, exact exceptions, and
required corrections in a separate patcher table.

Manual validation may change a result to PASS only when the user explicitly
provides that evidence. Label the evidence as manual rather than rewriting the
raw automated output.

## Report format

Produce Markdown with these sections:

1. Executive summary: current `PASS`, `FAIL`, and `N/A` totals.
2. Post-remediation validation table.
3. Patcher tests: `N/A`, P1, non-critical.
4. Other `N/A` results grouped by unsupported API, invalid input/precondition,
   and infrastructure/timing.
5. Final device health and genuine-product-failure conclusion.
6. Links to raw artifacts and the Pastry report.

Keep raw runner statuses separate from the classified product verdict. If raw
historical counts are useful, put them in a later historical section rather
than the executive summary.

## Validate project changes

```bash
buck2 test fbcode//neteng/test_infra/dne/taac/utils/driver_compatibility_checker/tests:test_driver_tester
buck2 test fbcode//neteng/test_infra/dne/taac/utils/driver_compatibility_checker/tests:test_netos_healthcheck_compatibility_checker
arc lint fbcode/neteng/test_infra/dne/taac/utils/driver_compatibility_checker
```
