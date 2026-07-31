# `docker/` — Docker build stack

## Files

| File | Purpose |
|---|---|
| `build-taac-image.sh` | Entry point. Builds `fboss-taac` from `Dockerfile.taac`. Auto-builds the FBOSS base image if missing. |
| `Dockerfile.taac` | Multi-stage dockerfile — builds fbthrift-python + fboss-thrift-defs + transitive deps + TAAC in a builder stage, then produces a slim CentOS Stream 9 runtime image. |
| `taac-entrypoint.sh` | `ENTRYPOINT` for `fboss-taac`. Resolves the per-config install hash + native lib paths and exports `PYTHONPATH` / `LD_LIBRARY_PATH` / `TAAC_OSS` before exec'ing the user command. |
| `taac-regen-thrift.sh` | Installed as `/usr/local/bin/taac-regen-thrift` inside the image. Regenerates Python thrift bindings from a bind-mounted workspace using the baked-in `thrift1` compiler. |
| `run_taac_docker.sh` | Developer wrapper. Shells into the container with workspace bind-mounted and `PYTHONPATH` pre-configured. `--regen` regenerates thrift bindings on entry. |

## Build flow

```
                FBOSS public Dockerfile
                  at the pinned fboss rev
                        │
                        │  (auto-built if missing)
                        ▼
                fboss-build-env:centos-<rev>         (shared base, ~4 GB)
                        │
                        ▼
                  Dockerfile.taac
                  build-taac-image.sh
                        │
                        ▼
                  fboss-taac
                  (vendor-shippable, ~1.3 GB)
```

The base image tag carries the fboss rev it was built from, taken from
`getdeps/manifests/fboss-thrift-defs` so one fboss commit supplies both the
build environment and the thrift defs. Bumping that pin yields a new tag,
which forces a base rebuild instead of silently reusing a stale image.

The full build takes ~22 min cold (folly + fizz + wangle + mvfst + fbthrift compiled from source). Docker's layer cache makes subsequent rebuilds fast when only TAAC source changes.

## Usage

**Build the TAAC image:**

```bash
./docker/build-taac-image.sh
```

**Custom tag:**

```bash
./docker/build-taac-image.sh --tag my-taac:v1
```

## When to rebuild

Docker's layer cache keeps the heavy dep compile cached when only TAAC source changes:

| Change | What rebuilds | Approximate cost |
|---|---|---|
| TAAC source (`.py`, `.thrift`, etc.) | Builder layers C–E + runtime COPYs | ~30 sec |
| `requirements.txt` | Builder layers D–E + runtime COPYs | ~1-2 min |
| `getdeps/manifests/*` or `scripts/setup_getdeps.sh` | Entire builder + runtime | ~22 min |
| `docker/taac-entrypoint.sh` or `docker/taac-regen-thrift.sh` | Runtime `COPY . /taac` + `cp` layer | ~1 sec |
| fboss pin in `getdeps/manifests/fboss-thrift-defs` | Base image tag changes → base + everything | ~28 min |
| `--no-cache` | Base image + entire builder + runtime | ~28 min |

### Refreshing the base image

`--no-cache` rebuilds the FBOSS base image as well as the TAAC layers. That
is deliberate: the base is stage 2 of `Dockerfile.taac` (the shipped runtime),
so its CentOS packages are part of what ships, and rebuilding is the only
thing that refreshes them — `quay.io/centos/centos:stream9` and the base's
`dnf install` lines are not pinned by anything here.

CI gets that refresh for free. Runners are ephemeral, so the base image is
never present and is rebuilt from live repos on every run (~5.5 min of the
~17 min build). Long-lived local machines do not, which is what `--no-cache`
is for: without it, a locally built base can sit unchanged for months.

Because the tag carries the fboss rev, each bump leaves the previous
`fboss-build-env:centos-<oldrev>` (~4 GB) behind on long-lived machines and
nothing prunes it. Clean up with `docker image rm fboss-build-env:centos-<oldrev>`,
or `docker image ls fboss-build-env` to see what has accumulated.

## Deps and the pins

The pinned rev in [`getdeps/manifests/fbthrift-python`](../getdeps/manifests/fbthrift-python) (`rev = <sha>`) is the single source of truth for the dep tree. `setup_getdeps.sh` clones the matching fbthrift tooling at that SHA so the build infrastructure stays in lockstep with the dep versions. The fbcode family is pinned as one snapshot — see `scripts/pin_fbcode_snapshot.py --check`, which CI runs before the build.

The fboss rev in [`getdeps/manifests/fboss-thrift-defs`](../getdeps/manifests/fboss-thrift-defs) does double duty: thrift defs, and the base image recipe.

**Bumping either pin:** edit the `rev = ...` line and commit. The next `build-taac-image.sh` run rebuilds the dep tree; bumping the fboss rev also changes the base image tag and so rebuilds the base.

## In-container iteration

After pulling the derived image, local edits to TAAC source or thrift schemas can be picked up by the running container without rebuilding the image. Use `run_taac_docker.sh`:

```bash
# Shell in with local source on PYTHONPATH (Python edits only)
./docker/run_taac_docker.sh

# Shell in + regenerate thrift bindings (for .thrift edits)
./docker/run_taac_docker.sh --regen

# Use a specific image
./docker/run_taac_docker.sh --image <image> --regen

# Run a one-shot command
./docker/run_taac_docker.sh run python3 -c 'import taac; print("ok")'
```

The wrapper bind-mounts the repo at `/workspace`, sets up `PYTHONPATH` so local source overrides baked-in modules, and (with `--regen`) regenerates thrift bindings automatically.

### How the overlay works

Python's namespace-package mechanism merges three contributors under `taac.__path__` (and friends):

  1. `/workspace` — bind-mounted source, overlays edited `.py` files
  2. `/tmp/regen/gen-python` — regenerated thrift bindings (only with `--regen`)
  3. `/scratch/installed/taac-*/lib/python3/site-packages/` — baked-in install tree (fallback for unchanged modules)

So source edits AND regenerated bindings both override the baked-in versions; everything else falls through to the image.

### Manual docker run

If you need more control than `run_taac_docker.sh` provides:

```bash
# Python source edits only
docker run --rm -it --network host \
    -v "$PWD":/workspace \
    fboss-taac \
    bash -c 'export PYTHONPATH=/workspace:$PYTHONPATH && exec bash'

# With thrift regen
docker run --rm -it --network host \
    -v "$PWD":/workspace \
    fboss-taac \
    bash -c 'taac-regen-thrift /workspace/taac/thrift /tmp/regen && export PYTHONPATH=/workspace:/tmp/regen/gen-python:$PYTHONPATH && exec bash'
```

## Where to look for details

- **Multi-stage layout + layer cache contract**: header comment in [`Dockerfile.taac`](Dockerfile.taac).
- **Entrypoint internals**: header in [`taac-entrypoint.sh`](taac-entrypoint.sh).
- **Script usage**: header comment in [`build-taac-image.sh`](build-taac-image.sh).
- **End-user usage**: top-level [`README.md`](../README.md).
