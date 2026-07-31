#!/usr/bin/env python3
"""Keep the fbcode dependency graph pinned to one consistent snapshot.

folly, wangle, fizz, mvfst and fbthrift are exported from a single fbcode
monorepo, so one internal diff can land in several repos at the same instant.
Upstream's getdeps manifests carry no `rev` for any of them, meaning getdeps
builds whatever is on main HEAD. Pin some but not all and you eventually
compile one half of a coordinated change against the other half.

This script does not know which dependencies exist. It walks the dependency
graph from our build targets and classifies each manifest by how it resolves,
so a dependency added upstream next year is caught the first time --check runs.

  --check          fail if any dependency in the graph floats (CI pre-flight)
  --write TAG      pin every git dependency to weekly release tag TAG

Run --help for the full option list.
"""

from __future__ import annotations

import argparse
import collections
import configparser
import functools
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, NamedTuple, NoReturn, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAY_DIR = os.path.join(REPO_ROOT, "getdeps", "manifests")

# Our getdeps build targets, as invoked by docker/Dockerfile.taac. These are
# ours to declare -- unlike the dependency set, which is discovered.
DEFAULT_ROOTS = ["fbthrift-python", "fboss-thrift-defs", "taac"]

# `taac` is this repo. The Dockerfile stubs .git/.projectid so getdeps builds
# it from the local checkout; an unpinned rev is correct here.
DEFAULT_ALLOW_FLOATING = ["taac"]

RAW_URL = ("https://raw.githubusercontent.com/facebook/fbthrift/{rev}"
           "/build/fbcode_builder/manifests/{name}")

FLOATING, PINNED, IMMUTABLE, SYSTEM, MISSING = (
    "floating", "pinned", "immutable", "system", "missing")


class Dep(NamedTuple):
    name: str
    kind: str
    url: Optional[str]
    rev: Optional[str]
    is_overlay: bool     # ours (and therefore ours to re-pin)
    via: str             # dependency path from a build target down to here


def die(msg: str) -> NoReturn:
    # flush first: stdout is block-buffered under a pipe, so without this the
    # error lands above its own context in CI logs
    sys.stdout.flush()
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------
# manifest loading
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def fetch_upstream(rev: str, name: str) -> Optional[str]:
    """Upstream manifest text at `rev`, or None if it does not exist there."""
    url = RAW_URL.format(rev=rev, name=name)
    # Retry transient failures: ~30 fetches per run against a shared-IP host,
    # and a 429 here would fail the pre-flight for a reason unrelated to pins.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                die(f"fetching {name}: HTTP {exc.code} from {url}")
        except OSError as exc:
            if attempt == 2:
                die(f"fetching {name}: {exc}")
        time.sleep(2 ** attempt)
    die(f"fetching {name}: exhausted retries")


class ManifestStore:
    """Resolves manifests the way setup_getdeps.sh assembles them: our overlay
    when we have one, otherwise upstream fbthrift at `upstream_rev`.

    Deliberately never reads a local build/fbcode_builder -- one left over from
    an older setup_getdeps.sh run would silently supply manifests at the wrong
    rev for anything we do not overlay.
    """

    def __init__(self, overlay_dir: str, upstream_rev: str) -> None:
        self.overlay_dir = overlay_dir
        self.upstream_rev = upstream_rev
        self._parsed: Dict[str, Optional[Tuple[configparser.ConfigParser, bool]]] = {}

    def raw(self, name: str) -> Optional[Tuple[str, bool]]:
        """(text, is_overlay), or None if the manifest exists nowhere."""
        path = os.path.join(self.overlay_dir, name)
        if os.path.exists(path):
            with open(path) as fh:
                return fh.read(), True
        text = fetch_upstream(self.upstream_rev, name)
        return (text, False) if text is not None else None

    def parsed(self, name: str) -> Optional[Tuple[configparser.ConfigParser, bool]]:
        """(parser, is_overlay), or None. Cached: walk() asks twice per name."""
        if name not in self._parsed:
            raw = self.raw(name)
            if raw is None:
                self._parsed[name] = None
            else:
                # bare keys in [dependencies], and some manifests repeat a
                # section header -- both need a non-strict parser
                parser = configparser.ConfigParser(allow_no_value=True,
                                                   strict=False)
                try:
                    parser.read_string(raw[0])
                except configparser.Error as exc:
                    die(f"parsing manifest {name}: {exc}")
                self._parsed[name] = (parser, raw[1])
        return self._parsed[name]


def sections_of(manifest: configparser.ConfigParser, family: str) -> List[str]:
    """Section names in `family`, conditional variants included.

    getdeps qualifies sections with build conditions -- [download.os=windows],
    [rpms.distro=fedora], and in principle [git.os=linux]. Matching the literal
    header only would misread those; for [git] that would mean a floating
    dependency classified as SYSTEM and silently passing --check.
    """
    return [s for s in manifest.sections()
            if s == family or s.startswith(family + ".")]


def value_in(manifest: configparser.ConfigParser, family: str,
             key: str) -> Optional[str]:
    for section in sections_of(manifest, family):
        value = manifest.get(section, key, fallback=None)
        if value:
            return value
    return None


def classify(name: str, store: ManifestStore, via: str) -> Dep:
    parsed = store.parsed(name)
    if parsed is None:
        return Dep(name, MISSING, None, None, False, via)
    manifest, is_overlay = parsed
    url = value_in(manifest, "git", "repo_url")
    if url:
        rev = value_in(manifest, "git", "rev")
        kind = PINNED if rev else FLOATING
        return Dep(name, kind, url, rev, is_overlay, via)
    # Exact [download] only, deliberately. Prefix-matching here would relabel
    # openssl/libsodium/boost-python/perl/jom as immutable on the strength of a
    # conditional download they do not use on linux (openssl's is
    # [download.not(any(os=linux, os=freebsd))]; it ships [rpms] for us).
    # Getting that right means evaluating getdeps' condition expressions for
    # our platform, which is a lot of machinery for a cosmetic count -- and
    # this split is cosmetic. The [git] prefix match above is the one that
    # affects the pass/fail decision.
    kind = IMMUTABLE if manifest.has_section("download") else SYSTEM
    return Dep(name, kind, None, None, is_overlay, via)


def walk(roots: List[str], store: ManifestStore) -> Dict[str, Dep]:
    """Depth-first walk of the transitive [dependencies] closure."""
    found: Dict[str, Dep] = {}

    def visit(name: str, ancestors: List[str]) -> None:
        if name in found:
            return
        found[name] = classify(name, store, " -> ".join(ancestors + [name]))
        parsed = store.parsed(name)
        if parsed is None:
            return
        manifest, _ = parsed
        for section in manifest.sections():
            # [dependencies] plus conditional variants such as
            # [dependencies.os=linux] and [dependencies.all(test=on,...)]
            if section == "dependencies" or section.startswith("dependencies."):
                for dep in manifest[section]:
                    visit(dep, ancestors + [name])

    for root in roots:
        visit(root, [])
    return found


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def ls_remote_tag(url: str, tag: str) -> Optional[str]:
    """Commit SHA for `tag` in `url`, or None if the tag does not exist.

    ls-remote needs no API token and has no rate limit. Annotated tags also
    report a `^{}` peeled ref; that is the commit we want.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-remote", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
            capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        die(f"git ls-remote {url} timed out after 60s")
    if proc.returncode != 0:
        die(f"git ls-remote {url} failed: {proc.stderr.strip()}")
    plain = peeled = None
    for line in proc.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.endswith("^{}"):
            peeled = sha.strip()
        elif ref:
            plain = sha.strip()
    return peeled or plain


def snapshot_path(overlay_dir: str) -> str:
    """Sits beside the overlays, so --overlay-dir redirects it too."""
    return os.path.join(os.path.dirname(os.path.abspath(overlay_dir)),
                        "FBCODE_SNAPSHOT")


def read_snapshot(overlay_dir: str) -> Optional[str]:
    path = snapshot_path(overlay_dir)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return None


# --------------------------------------------------------------------------
# overlay authoring
# --------------------------------------------------------------------------

OVERLAY_HEADER = """\
# GENERATED FILE -- do not hand-edit; scripts/pin_fbcode_snapshot.py rewrites
# the whole file (body from upstream, plus the rev), so local edits are lost.
# Re-pin: ./scripts/pin_fbcode_snapshot.py --write <tag>
# Snapshot: {tag} (upstream weekly release tag)
"""


def inject_rev(body: str, sha: str) -> str:
    """Insert or replace `rev =` in the [git] section."""
    if re.search(r"^rev\s*=", body, re.M):
        return re.sub(r"^rev\s*=.*$", f"rev = {sha}", body, count=1, flags=re.M)
    out, injected, in_git = [], False, False
    for line in body.splitlines(keepends=True):
        out.append(line)
        stripped = line.strip()
        if stripped.startswith("["):
            in_git = stripped == "[git]"
        elif in_git and not injected and stripped.startswith("repo_url"):
            out.append(f"rev = {sha}\n")
            injected = True
    if not injected:
        die("could not locate [git] repo_url to inject rev after")
    return "".join(out)


def write_overlay(name: str, tag: str, sha: str, body: str,
                  overlay_dir: str, dry_run: bool) -> str:
    """Write an overlay from an upstream body + rev. Returns an action word."""
    content = OVERLAY_HEADER.format(tag=tag) + inject_rev(body, sha)
    path = os.path.join(overlay_dir, name)
    existed = os.path.exists(path)
    if existed and open(path).read() == content:
        return "unchanged"
    if not dry_run:
        with open(path, "w") as fh:
            fh.write(content)
    return "updated" if existed else "created"


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def plural(n: int, word: str = "dependenc") -> str:
    return f"{n} {word}{'y' if n == 1 else 'ies'}"


def render_summary(deps: Dict[str, Dep], roots: List[str]) -> None:
    counts = collections.Counter(dep.kind for dep in deps.values())
    print(f"build targets: {', '.join(roots)}")
    print(f"dependency graph: {len(deps)} manifests")
    for kind in (FLOATING, PINNED, IMMUTABLE, SYSTEM, MISSING):
        if counts[kind]:
            print(f"  {kind:10} {counts[kind]}")


def mode_check(args: argparse.Namespace, deps: Dict[str, Dep]) -> int:
    allow = set(args.allow_floating)
    render_summary(deps, args.roots)

    failures = []
    for dep in sorted(deps.values()):
        if dep.kind == MISSING:
            failures.append(f"{dep.name}: no manifest found (reached via {dep.via})")
        elif dep.kind == FLOATING and dep.name not in allow:
            failures.append(
                f"{dep.name} has no pinned commit (tracks main HEAD)\n"
                f"      repo:  {dep.url}\n"
                f"      via:   {dep.via}")

    print()
    if failures:
        for msg in failures:
            print(f"FAIL: {msg}")
        print(f"\n{plural(len(failures))} unpinned. "
              f"Pin with: ./scripts/pin_fbcode_snapshot.py --write <tag>")
        return 1

    print("PASS: every git dependency resolves to a fixed commit; the rest "
          "are checksummed archives or system packages.")

    # Advisory tier: agreement with the recorded snapshot. Soft by design --
    # not every dependency rides the weekly train (fboss publishes no tags;
    # upstream pins glog to an unrelated SHA).
    snapshot = read_snapshot(args.overlay_dir)
    if not snapshot:
        print(f"\nnote: no "
              f"{os.path.relpath(snapshot_path(args.overlay_dir), REPO_ROOT)}; "
              "skipping snapshot-agreement check.")
        return 0

    print(f"\nsnapshot agreement ({snapshot}):")
    for dep in sorted(deps.values()):
        if dep.kind != PINNED or not dep.is_overlay or dep.url is None:
            continue
        tag_sha = ls_remote_tag(dep.url, snapshot)
        if tag_sha is None:
            print(f"  {dep.name:22} n/a     (no {snapshot} tag in this repo)")
        elif tag_sha == dep.rev:
            print(f"  {dep.name:22} ok      {tag_sha[:12]}")
        else:
            print(f"  {dep.name:22} DIFFERS pinned "
                  f"{dep.rev[:12] if dep.rev else '(none)'}, "
                  f"tag {tag_sha[:12]}")
    return 0


def mode_write(args: argparse.Namespace, deps: Dict[str, Dep]) -> int:
    tag, allow = args.write, set(args.allow_floating)
    render_summary(deps, args.roots)
    print(f"\npinning git dependencies to {tag}:")

    # Bodies come from upstream at this tag's fbthrift rev, so an upstream
    # [dependencies] edit is carried across rather than silently dropped.
    fbthrift = deps.get("fbthrift-python")
    if fbthrift is None or fbthrift.url is None:
        die("fbthrift-python is not in the dependency graph; cannot determine "
            "which upstream rev to read manifests from")
    body_rev = ls_remote_tag(fbthrift.url, tag)
    if body_rev is None:
        die(f"no {tag} tag in {fbthrift.url} -- is that a real weekly tag?")
    print(f"  reading upstream manifests at fbthrift {body_rev[:12]}\n")

    # Ours to re-pin: a git dependency we already overlay, or one that floats.
    # Resolve everything before writing, so a missing tag cannot leave the
    # overlays half-migrated.
    resolved, skipped, unpinnable = [], [], []
    for dep in sorted(deps.values()):
        if dep.url is None or dep.name in allow:
            continue
        if dep.kind == PINNED and not dep.is_overlay:
            continue          # upstream pins it itself (glog); leave alone
        body = fetch_upstream(body_rev, dep.name)
        if body is None:
            # No upstream manifest: ours alone (e.g. fboss-thrift-defs). Only
            # benign when it is already pinned -- otherwise --write would exit
            # 0 leaving something --check still fails on.
            note = "" if dep.kind == PINNED else "  (STILL UNPINNED)"
            print(f"  {dep.name:22} SKIP      hand-maintained (no upstream "
                  f"manifest){note}")
            if dep.kind == FLOATING:
                unpinnable.append(dep)
            continue
        sha = ls_remote_tag(dep.url, tag)
        if sha is None:
            skipped.append(dep)
            print(f"  {dep.name:22} SKIP      no {tag} tag in {dep.url}")
        else:
            resolved.append((dep, sha, body))

    if unpinnable:
        die(f"{plural(len(unpinnable))} floating with no upstream manifest "
            f"to regenerate from: {', '.join(d.name for d in unpinnable)}. Pin "
            f"by hand, or add to --allow-floating if intended.")
    if skipped and not args.allow_partial:
        die(f"{plural(len(skipped))} lack the {tag} tag, so this snapshot "
            f"cannot be applied consistently. Pin those by hand, or re-run "
            f"with --allow-partial to pin only the rest.")
    if not resolved:
        print("\n  nothing to pin.")
        return 0

    for dep, sha, body in resolved:
        action = write_overlay(dep.name, tag, sha, body,
                               args.overlay_dir, args.dry_run)
        print(f"  {dep.name:22} {action:9} {sha[:12]}")

    if not args.dry_run:
        with open(snapshot_path(args.overlay_dir), "w") as fh:
            fh.write("# GENERATED FILE -- do not hand-edit. The fbcode snapshot "
                     "every pinned\n# getdeps dependency shares; see "
                     "scripts/pin_fbcode_snapshot.py.\n"
                     f"{tag}\n")
        print(f"\nrecorded snapshot in "
              f"{os.path.relpath(snapshot_path(args.overlay_dir), REPO_ROOT)}")

    print("\nNext:")
    print("  1. Confirm the change that broke you is actually in this tag --")
    print("     weekly tags are cut before same-week fixes land.")
    print("  2. git diff getdeps/manifests/  (upstream may have changed the")
    print("     [dependencies] list, not just the rev)")
    print("  3. ./scripts/setup_getdeps.sh --force   (no-ops otherwise)")
    if args.dry_run:
        print("\n(--dry-run: nothing written)")
    return 0


def upstream_rev_for(overlay_dir: str) -> str:
    """The fbthrift rev to read upstream manifests at.

    Same rev setup_getdeps.sh uses for the fbcode_builder tooling, so the
    manifests we reason about match the ones the build will see. Falls back to
    main when nothing is pinned yet (bootstrapping a fresh overlay dir).
    """
    path = os.path.join(overlay_dir, "fbthrift-python")
    if os.path.exists(path):
        with open(path) as fh:
            match = re.search(r"^rev\s*=\s*(\S+)", fh.read(), re.M)
        if match:
            return match.group(1)
    return "main"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  %(prog)s --check\n"
               "  %(prog)s --write v2026.07.27.00 --dry-run\n")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true",
                        help="fail if any dependency floats (CI pre-flight)")
    action.add_argument("--write", metavar="TAG",
                        help="pin git dependencies to weekly tag TAG")
    parser.add_argument("--roots", nargs="+", default=DEFAULT_ROOTS,
                        help="getdeps build targets to walk from "
                             "(default: %(default)s)")
    parser.add_argument("--allow-floating", nargs="+",
                        default=DEFAULT_ALLOW_FLOATING,
                        help="manifests permitted to track HEAD "
                             "(default: %(default)s)")
    parser.add_argument("--overlay-dir", default=OVERLAY_DIR,
                        help="our manifest overlays (default: getdeps/manifests)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="--write: proceed even if some repos lack the tag")
    parser.add_argument("--dry-run", action="store_true",
                        help="--write: report changes without writing")
    args = parser.parse_args()

    store = ManifestStore(args.overlay_dir, upstream_rev_for(args.overlay_dir))
    deps = walk(args.roots, store)

    if args.check:
        return mode_check(args, deps)
    return mode_write(args, deps)


if __name__ == "__main__":
    sys.exit(main())
