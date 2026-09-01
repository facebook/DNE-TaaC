# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""Tests for the OSS coop patcher: the on-DUT mutation script (run for real
via subprocess) and the generated shell commands."""

import json
import subprocess
import sys

import pytest

from taac.driver import oss_coop_patcher as ocp


def run_script(tmp_path, base, patchers):
    (tmp_path / "base.conf").write_text(json.dumps(base))
    (tmp_path / "p.json").write_text(json.dumps(patchers))
    (tmp_path / "script.py").write_text(ocp._PATCH_SCRIPT)
    r = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "script.py"),
            str(tmp_path / "base.conf"),
            str(tmp_path / "out.conf"),
            str(tmp_path / "p.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[-1].startswith("OK ")
    return json.loads((tmp_path / "out.conf").read_text())


def patcher(name, func, args):
    return {"name": name, "py_func_name": func, "args": args}


def test_add_bgp_peers_both_shapes(tmp_path):
    concrete = [
        {
            "local_addr": "2001:db8:3::1",
            "peer_addr": "2001:db8:3::2",
            "peer_group_name": "PG1",
            "remote_as_4_byte": "65000",
            "description": "dl",
        },
        {
            "local_addr": "2001:db8:4::1",
            "peer_addr": "2001:db8:4::2",
            "peer_group_name": "PG1",
            "remote_as_4_byte": "65001",
            "description": "ul",
        },
    ]
    spec = [
        {
            "starting_ip": "10.0.0.0",
            "gateway_starting_ip": "10.0.0.1",
            "increment_ip": "0.0.0.2",
            "num_sessions": 2,
            "remote_as_4_byte": 65100,
            "remote_as_4_byte_step": 1,
            "peer_group_name": "PG1",
            "description": "spec",
        }
    ]
    out = run_script(
        tmp_path,
        {"peers": [{"peer_addr": "old"}]},
        [
            patcher("rm", "remove_bgp_peers", {"delete_all": "True"}),
            patcher("a", "add_bgp_peers", {"peer_configs": json.dumps(concrete)}),
            patcher("b", "add_bgp_peers", {"peer_configs": json.dumps(spec)}),
        ],
    )
    peers = out["peers"]
    assert [p["peer_addr"] for p in peers] == [
        "2001:db8:3::2",
        "2001:db8:4::2",
        "10.0.0.1",
        "10.0.0.3",
    ]
    # peer_id numbering restarts per description in the concrete branch
    assert peers[0]["peer_id"] == "dl:1"
    assert peers[1]["peer_id"] == "ul:1"
    assert [p["remote_as_4_byte"] for p in peers[2:]] == [65100, 65101]


def test_configure_vlans_merges_not_replaces(tmp_path):
    base = {
        "sw": {
            "interfaces": [{"vlanID": 2000, "ipAddresses": ["fd00::1/64"]}],
            "vlans": [{"id": 2000, "ipAddresses": ["fd00::1"]}],
        }
    }
    dl = {"vlan_id": 2000, "ip_addresses": ["fd00::1/64", "2001:db8:3::1/127"]}
    ul = {"vlan_id": 2000, "ip_addresses": ["fd00::1/64", "2001:db8:4::1/127"]}
    out = run_script(
        tmp_path,
        base,
        [
            patcher("dl", "configure_vlans", {"vlan2000": json.dumps(dl)}),
            patcher("ul", "configure_vlans", {"vlan2000": json.dumps(ul)}),
        ],
    )
    intf = out["sw"]["interfaces"][0]
    vlan = out["sw"]["vlans"][0]
    assert "2001:db8:3::1/127" in intf["ipAddresses"]
    assert "2001:db8:4::1/127" in intf["ipAddresses"]
    assert "2001:db8:3::1" in vlan["ipAddresses"]
    assert "2001:db8:4::1" in vlan["ipAddresses"]


def test_unknown_py_func_fails_loudly(tmp_path):
    with pytest.raises(NotImplementedError):
        ocp.register(
            "h1",
            "bgpcpp",
            ocp.OssPatcher(name="x", config_name="bgpcpp", py_func_name="nope"),
        )
    ocp.clear("h1")


def test_registry_register_replace_unregister():
    p = ocp.OssPatcher(name="a", config_name="bgpcpp", py_func_name="remove_bgp_peers")
    ocp.register("h2", "bgpcpp", p)
    ocp.register("h2", "bgpcpp_softdrain", p)  # ignored
    ocp.register("h2", "bgpcpp_drain", p)  # ignored
    ocp.register("h2", "bgpcpp", p)  # replaces, not duplicates
    assert ocp.pending_configs("h2") == ["bgpcpp"]
    assert len(ocp.list_patchers("h2", "bgpcpp")) == 1
    ocp.unregister("h2", "bgpcpp", "a")
    assert ocp.pending_configs("h2") == []
    ocp.clear("h2")


def test_build_commands():
    live, baseline, patched = ocp.variant_paths("bgpcpp")
    assert (live, baseline, patched) == (
        "/etc/coop/bgpcpp.conf",
        "/etc/coop/bgpcpp.baseline.conf",
        "/etc/coop/bgpcpp.patched.conf",
    )
    apply_cmd = ocp.build_apply_command(
        "bgpcpp",
        [ocp.OssPatcher(name="a", config_name="bgpcpp", py_func_name="remove_bgp_peers")],
    )
    # seeds the live path from the older-image sibling before snapshotting
    assert f"[ -e {live} ] || cp -a /etc/coop/bgpd.conf {live}" in apply_cmd
    assert f"[ -f {baseline} ] || cp -a {live} {baseline}" in apply_cmd
    activate = ocp.build_activate_command("bgpcpp")
    assert f"cp -a {patched} {live}" in activate
    assert activate.endswith("echo ACTIVATED")
    restore = ocp.build_restore_command("bgpcpp")
    assert f"cp -a {baseline} {live}" in restore
