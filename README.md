# DNE-Taac

Test As A Config (TAAC) — a configuration-driven network test automation framework.

## Overview

TAAC provides a declarative approach to network device testing, where test scenarios
are expressed as structured configurations rather than imperative scripts.

## Getting Started

See the [documentation](https://github.com/facebook/DNE-Taac) for setup instructions.

## Running TAAC modules under OSS

TAAC's Python modules (e.g. `taac.libs.taac_runner`) include Meta-internal imports that aren't shipped in this slice. Set `TAAC_OSS=1` so the imports take their OSS branch:

```bash
export TAAC_OSS=1
python3 -c 'import taac.libs.taac_runner; print("ok")'
```

Some runtime functionality is stubbed in OSS mode (NDS drainer, COOP patcher, ValidationStep, AristaSSHHelper, etc.) and will raise `NotImplementedError` if invoked on a code path that requires it. Imports succeed; trying to actually use those features fails.

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.
