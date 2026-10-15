# Standalone tictaac Binary

`scripts/build_tictaac_binary.sh` produces `dist/tictaac`, one executable that runs TAAC test configs on any x86_64 Linux host with glibc 2.34 or newer. It needs no Python, no Docker, and no shared library other than glibc.

```
$ ./scripts/build_tictaac_binary.sh
Built dist/tictaac
$ ldd dist/tictaac
        linux-vdso.so.1
        libm.so.6 => /lib64/libm.so.6
        libc.so.6 => /lib64/libc.so.6
        /lib64/ld-linux-x86-64.so.2
$ dist/tictaac run --test-config-json my_config.json --device-info-csv device_info.csv
```

Building needs only Docker on the build host. The script builds the FBOSS base image first if it is missing, through the same `docker/ensure-base-image.sh` that `docker/build-taac-image.sh` uses. A cold build takes about 75 minutes; Docker's layer cache makes a rebuild after a `taac/` change take about 15.

| Option | Default | Effect |
|---|---|---|
| `--output-dir DIR` | `dist` | Where `tictaac` is written |
| `--jobs N` | the smaller of the CPU count and RAM / 5 GiB | Build parallelism; each fbthrift compile job uses about 5 GiB |

The same binary runs unchanged on these minimal images, none of which has Python installed:

| Image | glibc |
|---|---|
| `ubuntu:24.04` | 2.39 |
| `debian:12-slim` | 2.36 |
| `centos:stream9-minimal` | 2.34 |

## Test Configs

The binary carries the framework, never the test configs. A config is a `TestConfig` serialized to JSON, passed with `--test-config-json <file>` or `-` for stdin, so a config change never needs a new binary.

```python
from taac.test_as_a_config import types as taac_types
from taac.utils.json_thrift_utils import thrift_to_json

open("my_config.json", "w").write(thrift_to_json(my_test_config))
```

## How It Is Built

| Stage | Script | Output |
|---|---|---|
| Static C libraries | `build_c_deps.sh` | OpenSSL, zlib, bzip2, xz, libffi as `.a` |
| Interpreter | `build_cpython.sh` | CPython with every stdlib extension compiled in |
| Rust extensions | `build_rust_extensions.sh` | `pydantic_core`, `cryptography`, `bcrypt` |
| C++ stack | `build_cpp_stack.sh` | folly, fizz, wangle, mvfst, fbthrift as `.a`, plus generated TAAC thrift |
| C extensions | `build_c_extensions.sh` | `_cffi_backend`, `nacl._sodium`, `grpc._cython.cygrpc` |
| thrift-python | `collect_thrift_builtins.sh` | the Cython modules of thrift-python and folly |
| Python payload | `assemble_payload.sh` | stdlib, TAAC, and the pinned wheels without native code, as a zip |
| Link | `link_tictaac.sh` | `launcher.c` and every builtin, statically linked, with the zip appended |
| Smoke | `smoke_test.sh` | `--version`, a setup-only run, and an invalid-config rejection |

Every native extension module is linked into the executable as a builtin and registered under its dotted name, for example `cryptography.hazmat.bindings._rust`. Rust and C extensions keep only their `PyInit_*` symbol global, so each keeps a private copy of its own runtime, exactly as separate `.so` files would. The launcher puts the executable itself on `sys.path`, and `zipimport` loads the appended payload.

All downloads are pinned by SHA-256 in `versions.sh`, `build-requirements*.txt`, and `runtime-requirements.txt`.
