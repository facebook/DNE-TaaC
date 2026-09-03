# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""From-scratch FBOSS config generators for the RBB SRv6 slice.

Pure, side-effect-free builders that emit the three JSON documents an imaged
MORGAN800CC FBOSS DUT needs to bring up the RBB SRv6 underlay:

  * ``agent_config``  -> ``/etc/coop/agent.conf``  (cfg::AgentConfig: ports/RIFs,
    port-channels, SRv6 mySidConfig/srv6Tunnels, static steering routes)
  * ``bgp_config``    -> ``/opt/bgpd/bgp.json`` (+ empty ``policy.json``)
  * ``openr_config``  -> ``/opt/openr/openr.conf``

Everything is derived from ``RbbTopology`` (device_info.csv + circuit_info.csv)
+ the ``TAAC_RBB_*`` address/SRv6 plan (``provision_plan``). Nothing lab-specific
is committed: defaults are RFC 3849 / RFC 5737 documentation ranges.

Design boundary (see ``agent_config`` docstring): the ASIC/board *hardware*
scaffolding -- the ``platform`` chip descriptor and the heavy SwitchConfig
sections that are board-generic plumbing (CPU/QoS queues, load balancers) -- are
NOT synthesizable from a topology CSV. They are sourced from the box's own
platform data at provision time. The generator owns 100% of the routing / L3 /
SRv6 / BGP / OpenR *semantics*; the immutable hardware base is an input.
"""
