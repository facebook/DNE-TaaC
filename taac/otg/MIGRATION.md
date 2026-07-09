# Migrating from IxNetwork to OTG on Keysight Hardware

Meta's chassis fleet currently runs IxNetwork (restpy). This document
covers what is (and isn't) required to run OTG workloads on existing
Keysight hardware.

## No chassis reconfiguration needed

There is no chassis-level "OTG mode" to flip. The physical hardware runs
its standard IxOS stack throughout. The difference between the two paths
is entirely in the software control plane — specifically, which software
holds the port reservation:

- If an IxNetwork session owns the port, only IxNetwork (and
  snappi-ixnetwork on top of it) can use it.
- If the port is released, KENG can take native ownership directly via
  IxOS, bypassing IxNetwork entirely.

To "switch" from IxNetwork to KENG on a given port, you release the
existing IxNetwork reservation and let KENG claim it — no reboot, no
re-image, no chassis reconfiguration.

One caveat for KENG: hardware-specific setup (e.g. AresONE-P multi-rate
configurations, hardware-accelerated MACsec) must still be configured
ahead of time via the chassis WebUI or IxOS REST API before KENG deploys
its traffic engines to that port.

## Two paths

|  | Path A: KENG native | Path B: snappi-ixnetwork |
|--|--|--|
| Chassis reconfiguration needed? | No | No |
| New controller stack on Linux host? | Yes (Docker Compose) | No |
| IxNetwork license needed? | No | Yes (existing) |
| KENG System Edition license? | Yes | No |
| OTG API compliance | Native (direct IxOS) | Translated (IxNetwork underneath) |
| Chassis awareness of OTG | Hardware programmed natively | Chassis sees a normal IxNetwork session |
| Hardware supported | Novus, AresONE | Novus, AresONE |

---

### Path A: KENG (Keysight Elastic Network Generator) — native OTG on hardware

KENG is the commercial edition of ixia-c with hardware chassis support.
The KENG controller talks directly to IxOS on the chassis, bypassing
IxNetwork entirely. It is not a wrapper — it is a completely distinct,
native control architecture.

**Hardware prerequisites**

- Load modules: Keysight **Novus** (100 GbE) or **AresONE** (400 GbE) only
- IxOS: **9.20 Patch 4** minimum; **10.80 EA or later** recommended
  (sub-10.80 triggers deprecation warnings as of v1.53.0-13)
- IxOS platform: **Linux-based IxOS only** — Windows IxOS is not supported

**Licensing**

Hardware access requires the **System Edition** license. Community,
Developer, and Team editions do not grant IxOS hardware access.

| Edition | Max Capacity | IxOS Hardware |
|--|--|--|
| Community | 4 × 1/10 GE | No (free) |
| Developer | 50 GE | No |
| Team | 400 GE | No |
| **System** | **800 GE** | **Yes** |

The license server is delivered as an OVA (VMware) or QCOW2 (KVM) VM
(2 vCPU, 4–8 GB RAM, 100 GB storage). It exposes HTTPS/443 for
activation and gRPC/7443 for controller license checkout. Containers
verify licensing at startup — check logs for
`Session successfully created with license server`.

See: [KENG licensing tiers](https://ixia-c.dev/reference/licensing/),
[KENG product page](https://www.keysight.com/us/en/products/network-test/protocol-load-test/keysight-elastic-network-generator.html)

**Controller deployment (Docker Compose)**

```yaml
services:
  keng-controller:
    image: ghcr.io/open-traffic-generator/keng-controller:1.58.0-1
    ports:
      - "40051:40051"
    environment:
      - LICENSE_SERVERS=<license-server-hostname-or-ip>
    depends_on:
      - keng-layer23-hw-server

  keng-layer23-hw-server:
    image: ghcr.io/open-traffic-generator/keng-layer23-hw-server:1.58.0-2

  otg-gnmi-server:          # optional — for gNMI telemetry
    image: ghcr.io/open-traffic-generator/otg-gnmi-server:1.58.0
    ports:
      - "50051:50051"
```

All images are public (`ghcr.io/open-traffic-generator/`); no registry
auth required. Deploy with `docker compose up -d`. Version numbers must
align — snappi, keng-controller, keng-layer23-hw-server, and
otg-gnmi-server are all released together with matching versions.

**Port location format**

```python
# format: "chassis_ip;card_number;port_number"
port = config.ports.add(name='p1', location='10.10.10.10;2;14')
```

See: [KENG hardware deployment guide](https://ixia-c.dev/tests-chassis-app/),
[hardware back-to-back example](https://otg.dev/examples/otg-examples/hw/ixhw-b2b/),
[ixia-c release notes](https://ixia-c.dev/releases/)

---

### Path B: snappi-ixnetwork — OTG translation layer over existing IxNetwork

A snappi plugin that translates OTG calls into IxNetwork REST API calls
at runtime — 100% client-side. No chassis changes and no new controller
stack. IxNetwork must stay installed and running (8.x+ with REST API
required). The chassis has no idea it is running an OTG test; to it,
the session looks like any standard IxNetwork session.

**Installation**

```bash
pip install "snappi[ixnetwork]"   # recommended
# or: pip install snappi-ixnetwork
```

**Connecting to an existing IxNetwork API Server**

```python
import snappi

api = snappi.api(
    location='https://<ixnetwork-api-server-host>:443',
    ext='ixnetwork',
    verify=False,   # skip TLS cert verification if needed
)
```

The `location` is the HTTPS address of your IxNetwork API Server
(Web Edition or standalone). Port location format is identical to KENG:
`chassis_ip;card_number;port_number`.

See: [snappi-ixnetwork on GitHub](https://github.com/open-traffic-generator/snappi-ixnetwork),
[snappi-ixnetwork on PyPI](https://pypi.org/project/snappi-ixnetwork/)

---

## Hardware compatibility matrix

| Load module | KENG (Path A) | snappi-ixnetwork (Path B) | Min IxOS |
|--|--|--|--|
| Novus (100 GbE) | Supported | Supported | 9.20 Patch 4 |
| AresONE (400 GbE) | Supported | Supported | 9.20 Patch 4 |
| AresONE-P | Supported | Supported | 9.20 Patch 4 |
| UHD400T (white-box) | Supported (Team/System) | N/A | N/A |
| Windows IxOS chassis | **Not supported** | N/A | — |

## Switching TAAC between backends

No chassis-side changes are required — set `traffic_generator_backend=OTG`
on the TestConfig and point `--ixia-api-server` at the OTG endpoint
(KENG controller on port 40051, or a snappi-ixnetwork-fronted IxNetwork
API Server). The default (`RESTPY`) continues to drive IxNetwork directly.

For other hardware vendors, any endpoint implementing the
[OTG API](https://github.com/open-traffic-generator/models) will work
with TAAC's OTG backend.

## References

| Resource | URL |
|--|--|
| ixia-c documentation hub | https://ixia-c.dev/ |
| KENG hardware setup | https://ixia-c.dev/tests-chassis-app/ |
| KENG licensing | https://ixia-c.dev/reference/licensing/ |
| ixia-c release notes | https://ixia-c.dev/releases/ |
| OTG spec and implementations | https://otg.dev/implementations/ |
| Hardware b2b example | https://otg.dev/examples/otg-examples/hw/ixhw-b2b/ |
| open-traffic-generator GitHub org | https://github.com/open-traffic-generator |
| snappi Python SDK | https://github.com/open-traffic-generator/snappi |
| snappi-ixnetwork | https://github.com/open-traffic-generator/snappi-ixnetwork |
| ixia-c core repo | https://github.com/open-traffic-generator/ixia-c |
| otg-examples | https://github.com/open-traffic-generator/otg-examples |
| KENG product page (Keysight) | https://www.keysight.com/us/en/products/network-test/protocol-load-test/keysight-elastic-network-generator.html |
