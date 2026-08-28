# DNE-Taac

Test As A Config (TAAC) — a configuration-driven network test automation framework. TAAC provides a declarative approach to FBOSS network device testing, where test scenarios are expressed as structured configurations rather than imperative scripts.

A test is a `TestConfig` containing one or more **playbooks**; a playbook runs against a **DUT** (device under test) and is composed of ordered **stages**; each stage is a list of **steps** — the smallest units of work (e.g. `RUN_SSH_COMMAND_STEP`, `DUMMY_STEP`, plus device-management ones). Stages express ordering and parallelism; playbooks group what runs against which device.


## Quick start

Smoke-tested via [facebook/fboss](https://github.com/facebook/fboss)'s public Docker images on **CentOS Stream 9**. Docker is the only host-side dependency.

```bash
# Build the vendor-shippable TAAC image (auto-builds base image if missing)
./docker/build-taac-image.sh
```

That single command builds the FBOSS CentOS base image if missing, compiles the full dep tree (folly, fizz, wangle, mvfst, fbthrift), builds TAAC, and produces `fboss-taac` — a self-contained image with all transitive deps baked in.

The normal command reuses the revision-tagged FBOSS/Thrift base image and
unchanged TAAC layers. Use `--rebuild-taac-image` to rebuild TAAC without its
layer cache, `--rebuild-base-image` to refresh the compiler/runtime base, or
`--no-cache` as the compatibility shortcut for rebuilding both.

### Validating a change

To build *and* verify in one step — the entry point CI and contributors should use:

```bash
# Build the image, then run unit tests + smoke test against it
./scripts/validate.sh
```

Run it with no arguments and it needs no registry, no credentials, and no host-side
state beyond Docker. Useful variants:

```bash
./scripts/validate.sh --skip-smoke              # unit tests only, skip the smoke test
./scripts/validate.sh --skip-tests              # build the image, run no tests
./scripts/validate.sh --pull --image IMAGE      # test a prebuilt image instead of building one
./scripts/validate.sh --dry-run                 # print the commands, execute nothing
```

Anything after `--` is forwarded verbatim to pytest, so pytest's own selection flags
work unchanged — `-k` filters by test name, for example:

```bash
./scripts/validate.sh -- -k retry               # run only tests whose name matches "retry"
./scripts/validate.sh -- taac/runner/tests/ -v  # run one directory, verbosely
```

`validate.sh` composes the two scripts either side of it — `docker/build-taac-image.sh`
to acquire an image and `scripts/run_tests.sh` to test one — so either can still be
driven directly when you want just one half.

The image's entrypoint sets `PYTHONPATH` and `LD_LIBRARY_PATH` automatically, so vendors can `docker run --rm fboss-taac python3 ...` with no host-side state. See [`docker/README.md`](docker/README.md) for the build-flow diagram and layer-cache contract.

For iterative work on TAAC source or thrift schemas in a bind-mounted workspace — no image rebuild required — see the in-container iteration section in [`docker/README.md`](docker/README.md) (Python source edits work via `PYTHONPATH`; thrift edits use the baked-in `taac-regen-thrift` helper).

### Build cost

First build takes ~22 min cold (mostly the deps compile). Docker's layer cache makes subsequent rebuilds after TAAC-only source changes finish in ~30 sec. See [`docker/README.md`](docker/README.md) for the layer cache contract and when to rebuild what.

## Outputs

Inside the `fboss-taac` image, generated thrift bindings + the TAAC Python source land under:

```
/scratch/installed/taac-<HASH>/lib/python3/site-packages/
```

They contain `taac/`, `ixia/`, `neteng/`, `facebook/`, `fb303/`. Each generated `thrift_types.py` ships a co-located `types.py` / `ttypes.py` / `clients.py` shim so legacy-style imports resolve.

The `<HASH>` suffix is getdeps' per-configuration cache key — it changes if you pass different `--extra-cmake-defines` to `getdeps.py build`.

## Using the bindings

The image's entrypoint automatically sets `PYTHONPATH` and `LD_LIBRARY_PATH`, so imports work out of the box:

```bash
docker run --rm fboss-taac python3 -c '
    from neteng.fboss.ctrl.thrift_types import NdpEntryThrift
    from taac.test_as_a_config.thrift_types import TestConfig
    print("ok")
'
```

## Running TAAC modules under OSS

TAAC's Python modules (e.g. `taac.libs.taac_runner`) include Meta-internal imports that aren't shipped in this slice. Set `TAAC_OSS=1` so the imports take their OSS branch:

```bash
export TAAC_OSS=1
python3 -c 'import taac.libs.taac_runner; print("ok")'
```

Some runtime functionality is stubbed in OSS mode (NDS drainer, COOP patcher, ValidationStep, AristaSSHHelper, etc.) and will raise `NotImplementedError` if invoked on a code path that requires it. Imports succeed; trying to actually use those features fails.

### Driving a minimal test

```python
import asyncio
from taac.test_as_a_config.thrift_types import (
    TestConfig, Playbook, Stage, Step, StepName, Endpoint, DeviceOsType,
)
from taac.libs.taac_runner import TaacRunner

cfg = TestConfig(
    name='smoke',
    basset_pool='',  # Meta-internal hardware reservation pool; '' is fine for OSS
    playbooks=[Playbook(
        name='dummy_playbook',
        stages=[Stage(steps=[Step(name=StepName.DUMMY_STEP)])],
    )],
    endpoints=[Endpoint(name='your-host', dut=True)],
    host_os_type_map={'your-host': DeviceOsType.FBOSS},
    startup_checks=[],
)

# skip_post_setup_wait skips a 180s interface-stabilization sleep
# that's only useful when booting real hardware.
async def main():
    runner = TaacRunner(test_config=cfg, skip_post_setup_wait=True)
    await runner.async_test_setUp()
    await runner.run_tests()

asyncio.run(main())
```

### Live-device smoke

`examples/smoke_live_device.py` runs the same shape against real
device(s), driving both a `DUMMY_STEP` playbook and a
`RUN_SSH_COMMAND_STEP` playbook. It expects `TAAC_OSS=1`, `TAAC_SSH_USER`,
and `TAAC_SSH_PASSWORD` to be set on the host — `run_taac_docker.sh`
auto-forwards any `TAAC_*` env var into the container, so keep secrets
out of inline `bash -c` strings (e.g. source them from a gitignored
file or a vault):

```bash
# Source the password from a file (chmod 600), not the command line.
export TAAC_OSS=1 TAAC_SSH_USER=netops
source ~/.taac-secrets  # exports TAAC_SSH_PASSWORD=...

./docker/run_taac_docker.sh run \
    python3 /workspace/examples/smoke_live_device.py \
        --device-info-csv /workspace/examples/topology/sample_device_info.csv \
        --circuit-info-csv /workspace/examples/topology/sample_circuit_info.csv \
        --command "uname -a"
```

The wrapper bind-mounts the repo at `/workspace`, sets `PYTHONPATH` to
include it, and runs `--network host` so internal-DNS hostnames resolve
inside the container.

Without `--hosts`, every hostname listed in `--device-info-csv` is used as a DUT. Pass `--hosts host1 host2` to run against a subset. `examples/topology/` ships sample CSVs as templates — copy them, replace the placeholder hostnames / OS column with your own fleet, and point `--device-info-csv` / `--circuit-info-csv` at your copies.

### Plugging in a custom driver

`DEVICE_OS_DRIVER_CLASS_MAP` ships with `FbossSwitch` registered for `DeviceOsType.FBOSS`. For other OS types (Arista, Cisco, etc.), register your own `AbstractSwitch` subclass:

```python
from taac.utils.driver_factory import register_driver_class
from taac.test_as_a_config.thrift_types import DeviceOsType
from my_pkg.my_driver import MyArista  # your subclass of AbstractSwitch

register_driver_class(DeviceOsType.ARISTA_OS, MyArista)
```

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.
