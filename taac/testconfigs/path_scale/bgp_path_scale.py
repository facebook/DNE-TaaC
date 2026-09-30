# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Role-agnostic BGP path-scale stress specification.

Puts a DUT into a defined BGP stressed state described by WHAT arrives and HOW,
independent of device role. A spec answers five questions:

1. **Prefix mix**        -- which prefixes, at which mask lengths, in what shape
2. **Path count**        -- how many paths each prefix is received over
3. **Paths per session** -- how those paths spread across BGP sessions
4. **Ingress policy**    -- accept prefixes on the basis of community
5. **Egress policy**     -- re-advertise a SUBSET to a given peer group

(2) and (3) are separate knobs on purpose. The same 256-way ECMP can arrive as
256 sessions x 1 path or 1 session x 256 add-paths; those stress peer/session
management versus add-path handling and yield the same FIB width, so pinning
only the width under-specifies the test.

``ReceiveGroup.distribution`` is the other axis:

- ``SHARED``      every session advertises the SAME prefixes -> N-way ECMP.
                  Few unique prefixes, many paths each.
- ``PARTITIONED`` the prefix set is SPLIT across sessions -> many unique
                  prefixes, few paths each.

The same session count produces wildly different RIB shapes under the two, so a
spec must say which. Both are real: a spine layer re-advertising the same
aggregates looks SHARED; a leaf layer each owning its own subnets looks
PARTITIONED.

## Measuring the result

Rib-in and rib-out are separate legs and must be measured separately. They do
not contribute equally -- in prior scale work bgpd's footprint was dominated by
rib-in, with rib-out close to free -- so a single combined number attributes
cost to the wrong axis. Toggle the route ranges (``Active``) to isolate them.

Read memory from the on-device kernel cgroup, which is authoritative::

    /sys/fs/cgroup/workload.slice/workload-<svc>.service/memory.{current,peak}
    svc in: bgpd fsdb fboss_sw_agent fboss_hw_agent@0

- **Restart bgpd between legs.** Its RSS does NOT shrink when routes are
  withdrawn (allocator retention), so without a restart a later smaller leg
  reads inflated and looks like a leak.
- Use bgpd's ``memory.peak`` only if it was restarted for that leg; the agents
  are NOT restarted, so their ``peak`` is stale carryover -- use ``current``.
- **Do not use ODS ``max()``** on ``cgroup.slice.workload.*.memory.current``: it
  aggregates sub-series and reports bogus highs. Use ``avg()`` or read on-device.
- ``ps`` RSS is not the cgroup number; prefer the cgroup.

## Resource budgets to check BEFORE running

- **ARS supergroup**: caps UNIQUE next-hop addresses device-wide, charged once
  per distinct next-hop set. Adding prefixes over an existing set is free;
  adding distinct next hops is not. Other consumers (live fabric adjacencies)
  spend from the same budget, so a DUT carrying production peering may have
  little left. ``supergroup_members()`` reports the claim; read the enforced
  limit from the ASIC rather than assuming.
- **bgpd ``--max_rss_size``** in ``bgpd.service`` bounds bgpd RSS and it exits
  above the cap. Raise it before a run that will exceed the default.
- **``switch_limit_config.prefix_limit``** must exceed the RIB scale.
- **FIB programming**: on a bgpd image that programs the RIB into the FIB, a
  full sync larger than the HW can hold fails with ``FbossFibUpdateError`` and
  bgpd re-arms ``FibProgrammingHolddown`` forever. Control-plane scale images
  that skip FIB programming avoid it. Know which image is under test.
"""

import ipaddress
import os
import typing as t
from dataclasses import dataclass, field
from enum import Enum

from taac.testconfigs.ai_bb.prefix_block_spec import (
    format_ipv6_full,
    nexthop_pool,
    PrefixBlockSpec,
    write_block_injection_csv,
    write_injection_csv,
)


# BgpPolicyAtomicMatchType (configerator/structs/neteng/bgp_policy/thrift)
MATCH_COMMUNITY_LIST: int = 3
MATCH_PREFIX_LIST: int = 5
MATCH_ALWAYS: int = 20

# BgpPolicyActionType. NOTE 5=PERMIT exists but is NOT used on bgpcpp: the
# statement defaults to DENY and a matched term carrying only "set" actions (or
# no action at all) implicitly permits. Emitting an explicit PERMIT is the wrong
# idiom for this device -- only 6=DENY is ever stated outright.
ACTION_COMMUNITY: int = 2
ACTION_SET_LOCAL_PREF: int = 3
ACTION_ORIGIN: int = 4
ACTION_DENY: int = 6
ACTION_CONTINUE: int = 7

COMMUNITY_ACTION_ADD: int = 1

# routing_policy.BooleanOperator
BOOL_AND: int = 1
BOOL_OR: int = 2


class Distribution(Enum):
    """How a prefix set maps onto the sessions that advertise it."""

    # Every session advertises the whole set -> N-way ECMP on each prefix.
    SHARED = "shared"
    # The set is split across sessions -> unique prefixes, few paths each.
    PARTITIONED = "partitioned"


@dataclass(frozen=True)
class ReceiveGroup:
    """One rib-in group: a prefix mix arriving over a set of sessions."""

    name: str
    blocks: t.Sequence[PrefixBlockSpec]
    sessions: int
    distribution: Distribution
    # Paths contributed per session per prefix. 1 unless the session uses
    # add-path to deliver several next hops for the same prefix.
    paths_per_session: int = 1
    # Community every prefix in this group carries; what the ingress policy
    # matches on.
    community: t.Optional[str] = None
    # Next-hop pool base. Each session gets `paths_per_session` addresses.
    nexthop_base: str = ""
    nexthop_step: int = 1

    def __post_init__(self) -> None:
        if self.sessions < 1:
            raise ValueError(f"{self.name}: sessions must be >= 1")
        if self.paths_per_session < 1:
            raise ValueError(f"{self.name}: paths_per_session must be >= 1")
        if not self.nexthop_base:
            raise ValueError(f"{self.name}: nexthop_base is required")
        if self.distribution is Distribution.PARTITIONED:
            total = sum(b.total for b in self.blocks)
            if total % self.sessions:
                raise ValueError(
                    f"{self.name}: PARTITIONED needs the prefix count ({total}) "
                    f"to divide across sessions ({self.sessions}); otherwise "
                    "sessions carry unequal shares and the per-session scale is "
                    "not what the spec claims."
                )

    @property
    def unique_prefixes(self) -> int:
        return sum(b.total for b in self.blocks)

    @property
    def paths_per_prefix(self) -> int:
        """ECMP width the DUT sees for one prefix in this group."""
        if self.distribution is Distribution.SHARED:
            return self.sessions * self.paths_per_session
        return self.paths_per_session

    @property
    def total_paths(self) -> int:
        if self.distribution is Distribution.SHARED:
            return self.unique_prefixes * self.sessions * self.paths_per_session
        return self.unique_prefixes * self.paths_per_session

    @property
    def nexthop_count(self) -> int:
        """Distinct next-hop addresses this group needs."""
        return self.sessions * self.paths_per_session

    def nexthops(self) -> t.List[str]:
        return nexthop_pool(self.nexthop_base, self.nexthop_count, self.nexthop_step)

    def session_nexthops(self, i: int) -> t.List[str]:
        if not 0 <= i < self.sessions:
            raise IndexError(f"{self.name}: session {i} out of range")
        w = self.paths_per_session
        return self.nexthops()[i * w : (i + 1) * w]

    def session_blocks(self, i: int) -> t.List[PrefixBlockSpec]:
        """The prefixes session `i` advertises.

        SHARED -> the whole set. PARTITIONED -> this session's slice, carved by
        splitting each block's contiguous runs so every session still advertises
        well-formed blocks (which is what makes block-mode CSV encoding work).
        """
        if self.distribution is Distribution.SHARED:
            return list(self.blocks)

        out: t.List[PrefixBlockSpec] = []
        for b in self.blocks:
            if b.blocks % self.sessions:
                raise ValueError(
                    f"{self.name}: PARTITIONED needs each spec's block count "
                    f"({b.blocks}) to divide across sessions ({self.sessions})"
                )
            per = b.blocks // self.sessions
            root = format_ipv6_full(
                ipaddress.IPv6Address(
                    int(ipaddress.IPv6Address(b.root)) + i * per * b.parent_size
                )
            )
            out.append(
                PrefixBlockSpec(
                    root=root,
                    root_mask=b.root_mask,
                    blocks=per,
                    parent_mask=b.parent_mask,
                    prefixes_per_block=b.prefixes_per_block,
                    prefix_length=b.prefix_length,
                    prefix_type=b.prefix_type,
                )
            )
        return out


@dataclass(frozen=True)
class AdvertiseSpec:
    """(5) Re-advertise a subset of received prefixes to one peer group."""

    peer_group: str
    policy_name: str
    match_communities: t.Sequence[str] = ()
    match_prefixes: t.Sequence[str] = ()
    set_community: t.Optional[str] = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.match_communities and not self.match_prefixes:
            raise ValueError(
                f"{self.policy_name}: an AdvertiseSpec selecting nothing exports "
                "everything; state the subset explicitly."
            )


@dataclass(frozen=True)
class PathScaleSpec:
    """A complete description of the stressed state to put a DUT into."""

    name: str
    receive: t.Sequence[ReceiveGroup]

    # (4) ingress: accept on the basis of community
    accept_communities: t.Sequence[str] = ()
    ingress_policy_name: str = ""

    # (5) egress
    advertise: t.Sequence[AdvertiseSpec] = field(default_factory=tuple)

    # Prefixes the DUT ORIGINATES for the rib-out leg, if any.
    originate: t.Sequence[PrefixBlockSpec] = field(default_factory=tuple)

    # Coarse mask at which originated space must differ from received space.
    # See _check_origination_disjoint for why block-level disjointness is not
    # enough. Widen or narrow per addressing plan.
    separation_mask: int = 16

    def __post_init__(self) -> None:
        if self.accept_communities and not self.ingress_policy_name:
            raise ValueError(f"{self.name}: accept_communities needs a policy name")

        # Every received community must be accepted, or the DUT silently drops
        # that whole group and the test measures nothing.
        for g in self.receive:
            if g.community and self.accept_communities:
                if g.community not in self.accept_communities:
                    raise ValueError(
                        f"{self.name}: group {g.name} carries {g.community} which "
                        f"is not in accept_communities "
                        f"{list(self.accept_communities)}; the DUT would drop it."
                    )

        # Originated space must be coarsely separated from received space --
        # see _check_origination_disjoint.
        self._check_origination_disjoint()

    def _check_origination_disjoint(self) -> None:
        """Originated space must be well separated from received space.

        Block-level non-overlap is NOT enough. Prior scale work saw rib-out
        advertisement suppressed almost entirely when the originated blocks sat
        in the same coarse space as the received blocks, even though the
        individual networks did not overlap; moving origination to a different
        high-order block restored it.

        So the rule is separation at a COARSE mask, not mere disjointness.
        ``separation_mask`` makes that explicit and tunable rather than hidden.
        """
        if not self.originate:
            return
        m = self.separation_mask
        recv = {
            ipaddress.IPv6Network(f"{b.root}/{m}", strict=False)
            for g in self.receive
            for b in g.blocks
        }
        for o in self.originate:
            on = ipaddress.IPv6Network(f"{o.root}/{m}", strict=False)
            if on in recv:
                raise ValueError(
                    f"{self.name}: originated {o.root} shares /{m} block {on} "
                    "with received space. Origination sharing coarse space with "
                    "rib-in has been observed to suppress rib-out advertisement "
                    "even when the individual networks do not overlap. "
                    f"Originate from a different /{m}."
                )

    # ---- totals -----------------------------------------------------------

    @property
    def total_unique_prefixes(self) -> int:
        return sum(g.unique_prefixes for g in self.receive)

    @property
    def total_rib_in_paths(self) -> int:
        return sum(g.total_paths for g in self.receive)

    @property
    def total_sessions(self) -> int:
        return sum(g.sessions for g in self.receive)

    def supergroup_members(self) -> int:
        """Unique next-hop addresses claimed from the ARS budget device-wide.

        Only MULTI-path groups count. ``checkAndUpdateGenericEcmpResource``
        reaches ``wouldExceedSuperGroupLimit`` solely when ``nhSet.size() > 1``,
        so a group delivering one path per prefix creates single-next-hop routes
        -- not ECMP groups -- and spends nothing from the supergroup, however
        many sessions it uses. Counting its next hops would badly overstate the
        claim for a PARTITIONED-heavy spec.
        """
        return sum(g.nexthop_count for g in self.receive if g.paths_per_prefix > 1)

    # ---- CSV generation ---------------------------------------------------

    def write_csvs(
        self, out_dir: str, block_mode: bool = True
    ) -> t.List[t.Tuple[str, str, int]]:
        """Per-session CSVs. Returns [(group, path, rows)].

        ``block_mode`` emits one row per (block x next-hop) and lets IxNetwork
        expand the run via NumberOfAddresses/PrefixAddrStep -- roughly
        ``prefixes_per_block`` times fewer rows. Row count, not prefix count, is
        what trips the IXIA port CPU ("Port <x> is not CPU ready"), so this is
        what makes large sets loadable.

        ``NumberOfAddresses`` is a pool-wide scalar, so blocks of differing size
        go to separate CSVs (hence separate pools).
        """
        os.makedirs(out_dir, exist_ok=True)
        out: t.List[t.Tuple[str, str, int]] = []
        for g in self.receive:
            for s in range(g.sessions):
                nhs = g.session_nexthops(s)
                groups: t.Dict[int, t.List[PrefixBlockSpec]] = {}
                for b in g.session_blocks(s):
                    groups.setdefault(b.prefixes_per_block, []).append(b)
                for count, blocks in sorted(groups.items()):
                    tag = f"{g.name}_s{s}" + (f"_n{count}" if len(groups) > 1 else "")
                    path = os.path.join(out_dir, f"{self.name}_{tag}.csv")
                    if block_mode:
                        write_block_injection_csv(path, blocks, next_hop=nhs)
                    else:
                        write_injection_csv(path, blocks, next_hop=nhs)
                    with open(path) as fh:
                        rows = sum(1 for _ in fh) - 1
                    out.append((g.name, path, rows))
        return out

    # ---- policy generation ------------------------------------------------

    @staticmethod
    def _permit_action() -> t.Dict[str, t.Any]:
        """A term that permits.

        bgpcpp statements default to DENY; a matched term carrying only "set"
        actions -- or none -- implicitly permits. An explicit PERMIT (type 5) is
        NOT the idiom here. Returning an empty action dict keeps that intent
        visible at the call site.
        """
        return {}

    def ingress_policy_args(self) -> t.Optional[t.Dict[str, t.Any]]:
        """(4) Accept received prefixes on the basis of community.

        kwargs for the ``add_bgp_policy_statement`` COOP patcher.

        SCHEMA TRAP: the patcher docstring shows ``atomic_matches``, but
        ``_create_policy_match`` reads ``match_entries``. The documented name
        yields a policy with no matches, which permits nothing and looks exactly
        like the DUT dropping every route.
        """
        if not self.accept_communities:
            return None
        return {
            "name": self.ingress_policy_name,
            "description": (
                f"{self.name}: accept prefixes carrying "
                f"{', '.join(self.accept_communities)}"
            ),
            "policy_entries": [
                {
                    "name": f"{self.ingress_policy_name}_ACCEPT_BY_COMMUNITY",
                    "policy_matches": [
                        {
                            "match_logic_type": BOOL_OR,
                            "match_entries": [
                                {
                                    "type": MATCH_COMMUNITY_LIST,
                                    "community_list": {
                                        "community_list": {
                                            "name": f"{self.ingress_policy_name}_CL",
                                            "description": f"{self.name} accepted",
                                            "boolean_operator": BOOL_OR,
                                            "communities": list(
                                                self.accept_communities
                                            ),
                                        }
                                    },
                                }
                            ],
                        }
                    ],
                    "policy_action_entries": [self._permit_action()],
                    "term_miss_action": "NEXT_TERM",
                }
            ],
        }

    def egress_policy_args(self) -> t.List[t.Dict[str, t.Any]]:
        """(5) Advertise a subset of received prefixes to a peer group."""
        out: t.List[t.Dict[str, t.Any]] = []
        for adv in self.advertise:
            match_entries: t.List[t.Dict[str, t.Any]] = []
            if adv.match_communities:
                match_entries.append(
                    {
                        "type": MATCH_COMMUNITY_LIST,
                        "community_list": {
                            "community_list": {
                                "name": f"{adv.policy_name}_CL",
                                "description": f"{adv.policy_name} communities",
                                "boolean_operator": BOOL_OR,
                                "communities": list(adv.match_communities),
                            }
                        },
                    }
                )
            if adv.match_prefixes:
                match_entries.append(
                    {
                        "type": MATCH_PREFIX_LIST,
                        "prefix_list": {
                            "prefix_list": {
                                "name": f"{adv.policy_name}_PL",
                                "description": f"{adv.policy_name} prefixes",
                                "prefixes": list(adv.match_prefixes),
                            }
                        },
                    }
                )

            action = self._permit_action()
            if adv.set_community:
                action = {
                    "type": ACTION_COMMUNITY,
                    "community_actions": [
                        {
                            "type": COMMUNITY_ACTION_ADD,
                            "community_name": adv.set_community,
                        }
                    ],
                }

            out.append(
                {
                    "name": adv.policy_name,
                    "description": (
                        adv.description
                        or f"{self.name}: export subset to {adv.peer_group}"
                    ),
                    "policy_entries": [
                        {
                            "name": f"{adv.policy_name}_EXPORT_SUBSET",
                            "policy_matches": [
                                {
                                    # AND when both community and prefix are
                                    # given: the subset is their intersection.
                                    "match_logic_type": (
                                        BOOL_AND if len(match_entries) > 1 else BOOL_OR
                                    ),
                                    "match_entries": match_entries,
                                }
                            ],
                            "policy_action_entries": [action],
                            "term_miss_action": "NEXT_TERM",
                        }
                    ],
                }
            )
        return out

    # ---- reporting --------------------------------------------------------

    def describe(self) -> str:
        lines = [f"PathScaleSpec {self.name!r}", "  rib-in:"]
        for g in self.receive:
            lines.append(
                f"    {g.name:<16} {g.unique_prefixes:>8} prefixes  "
                f"{g.sessions:>4} sessions x {g.paths_per_session} path  "
                f"{g.distribution.value:<11} -> {g.paths_per_prefix:>4}-way, "
                f"{g.total_paths:>9} paths   comm={g.community or '-'}"
            )
        lines += [
            f"    {'TOTAL':<16} {self.total_unique_prefixes:>8} prefixes  "
            f"{self.total_sessions:>4} sessions                       "
            f"{self.total_rib_in_paths:>9} paths",
            f"  ARS members (unique next-hops, device-wide): "
            f"{self.supergroup_members()}",
        ]
        if self.originate:
            lines.append(
                f"  originate: {sum(b.total for b in self.originate)} prefixes"
            )
        for adv in self.advertise:
            sel = []
            if adv.match_communities:
                sel.append(f"comm={list(adv.match_communities)}")
            if adv.match_prefixes:
                sel.append(f"pfx={list(adv.match_prefixes)}")
            lines.append(f"  export -> {adv.peer_group}: {'; '.join(sel)}")
        lines.append(
            f"  accept communities: {', '.join(self.accept_communities) or '-'}"
        )
        return "\n".join(lines)
