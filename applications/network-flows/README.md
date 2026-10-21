# Home network flows

chlorine samples VLAN 10 in both directions at 1:100 with Host sFlow. Only the
LAN interface is sampled; MAP-E, WARP and WAN encapsulation are not counted again.
UDP/6343 goes to the internal-only IPv4 LB `172.16.3.12`; NodePorts are disabled
and the Service source range allows only chlorine (`172.16.3.1`). L2 announcements
use `externalTrafficPolicy: Local` with one collector on every eligible L2
announcement node (the control-plane nodes). This keeps chlorine's source IP
through to the Pod and needs no node/world ingress exception. Keep the DaemonSet
node selector aligned with the L2 announcement policy when adding nodes. L2
announcements do not track local endpoint readiness: a receiver restart on the
announcing node can briefly lose UDP samples. Each receiver uses about 460MiB
with the full ASN map; three nodes use about 1.4GiB in total. A datagram is sent to
one announcing node, not copied to all receivers. Schema setup uses a database
advisory lock to serialize receiver startup.

`sfacctd` identifies upload/download using chlorine's LAN MAC
`00:e0:b4:6c:80:87`. Replace the direction map if the router NIC changes. It stores
one-minute aggregates in a dedicated CNPG database on iSCSI. IPtoASN's IPv4/IPv6
maps are downloaded at startup and atomically refreshed daily (the previous map
survives a failed refresh). ASN values are resolved at ingestion; a separate small enrichment worker refreshes
IPtoASN organization names daily. Restarting a Pod requires a successful initial ASN download.

Grafana's `Traffic / Home network` dashboard groups devices by MAC, so IPv6
privacy addresses do not create separate device nodes. The address table retains
IP detail. Device labels use chlorine's active DHCP hostname via MAC-specific
`home.arpa` DNS aliases, refreshed every minute. This also names IPv6 privacy
addresses without joining historical IPv4 leases. Devices that omit their DHCP
hostname fall back to their MAC; randomized MACs remain separate devices. Duplicate
hostnames include the MAC to distinguish them. AS labels use organization names,
falling back to AS numbers. Address tables show PTR names where available; public
DNS cannot necessarily identify the application or website behind an address.

The enrichment image is built by `Flow enrichment image` and published to GHCR;
keep its version tag in the workflow and Deployment aligned when changing it.
It uses eight DNS workers, two-second lookup deadlines and at most 500 uncached
addresses per refresh, prioritizing recent traffic. PTR successes are cached for
5 minutes to 24 hours, missing records for one hour. Local DHCP DNS uses only
chlorine's existing DNS listener at `172.16.2.1`; public PTR uses cluster DNS.
Cached addresses and inactive device metadata are pruned after seven days.
Enrichment failure does not stop flow ingestion. Service labels are protocol/port, not application identification.
Internal IPv4, non-global IPv6 and destinations in the device's delegated /56
are excluded from the view. This relies on chlorine's /56 DHCP-PD allocation and
continues across prefix changes without updating a fixed address list.

Counters are estimates normalized by sfacctd exactly once. Sampled frame bytes
and interface counters do not have identical overhead; compare trends rather
than exact equality. Short or low-volume flows can be missed. UDP collection and
in-memory aggregation do not guarantee delivery during restarts or DB outages.
The collector does not persist packet payloads. Aggregates (including remote IPs)
are deleted hourly after seven days; PostgreSQL autovacuum reuses freed space.

The `flow_reader` role can only SELECT the normalized view and label metadata. Its credentials are
stored in the `materia-applications/network-flows-reader` 1Password item; scoped
Operator RBAC and admission reference maps explicitly permit the two Secret
targets. Grafana requires login globally, including existing dashboards.

Deploy materia first (namespace, Operator permissions/admission, DB, collector,
Grafana and LB allocation), then chlorinate. Check the two generated reader
Secrets without printing their values, CNPG's role status, and collector logs.
After enabling the exporter, verify both directions and IPv4/IPv6 in the DB,
check the dashboard and compare with chlorine's interface counters. Do not inject
test samples into the production collector.

Run the disposable Docker integration test with `bash tests/network-flows.sh`.
It sends synthetic sFlow packets and checks sampling normalization, direction,
IPv6 PD changes, internal traffic exclusion and read-only access.

## Dashboard layout

The overview uses mirrored download/upload bandwidth, IPv4/IPv6 share, the
Sankey, top device/AS bars and AS traffic stacked over time. Service-port names
are conventional port hints, not application detection. Select a Device or click
its name in Device activity to focus all traffic panels; All devices resets it.
Bandwidth and Device activity deliberately show both directions. Address details
are collapsed by default; all counters are sampling-based estimates.

The layout takes inspiration from [Akvorado's flow distributions and stacked
AS time series](https://github.com/akvorado/akvorado/blob/main/console/data/docs/52-console.md)
and [ntopng's top talkers and host drilldown](https://www.ntop.org/guides/ntopng/user_interface/network_interface/dashboard/dashboard.html).
It uses Grafana's built-in panels plus the existing NetSage Sankey plugin.

The same dashboard includes Chlorine Router health and measured VLAN-10 bandwidth,
plus Ping Pong latency and expandable diagnostics. Device and Direction apply to
flow panels only; router/probe panels always cover the whole network. Shared time
range and crosshair support comparison without equating interface totals with
sampled external-flow counters.
