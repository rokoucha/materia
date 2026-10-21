# Home network flows

chlorine samples VLAN 10 in both directions at 1:100 with Host sFlow. Only the
LAN interface is sampled; MAP-E, WARP and WAN encapsulation are not counted again.
UDP/6343 goes to the internal-only IPv4 LB `172.16.3.12`; NodePorts are disabled
and the Service source range allows only chlorine (`172.16.3.1`). L2 announcements
use `externalTrafficPolicy: Cluster`, so the Pod policy also permits node forwarding.

`sfacctd` identifies upload/download using chlorine's LAN MAC
`00:e0:b4:6c:80:87`. Replace the direction map if the router NIC changes. It stores
one-minute aggregates in a dedicated CNPG database on iSCSI. IPtoASN's IPv4/IPv6
maps are downloaded at startup and atomically refreshed daily (the previous map
survives a failed refresh). ASN values are resolved at ingestion; labels initially
show AS numbers. Restarting a Pod requires a successful initial ASN download.

Grafana's `Traffic / Home network flows` dashboard groups devices by MAC, so IPv6
privacy addresses do not create separate device nodes. The address table retains
IP detail. Service labels are protocol/port, not application identification.
Internal IPv4, non-global IPv6 and destinations in the device's delegated /56
are excluded from the view. This relies on chlorine's /56 DHCP-PD allocation and
continues across prefix changes without updating a fixed address list.

Counters are estimates normalized by sfacctd exactly once. Sampled frame bytes
and interface counters do not have identical overhead; compare trends rather
than exact equality. Short or low-volume flows can be missed. UDP collection and
in-memory aggregation do not guarantee delivery during restarts or DB outages.
The collector does not persist packet payloads. Aggregates (including remote IPs)
are deleted hourly after seven days; PostgreSQL autovacuum reuses freed space.

The `flow_reader` role can only SELECT the normalized view. Its credentials are
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
