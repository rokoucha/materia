WITH selected AS (
  SELECT device_mac AS device, remote_as,
         CASE WHEN ip_proto IN (6,17) THEN
           CASE WHEN ip_proto=6 THEN 'TCP/' ELSE 'UDP/' END || service_port::text
         ELSE 'IP/' || ip_proto::text END AS service, bytes
  FROM traffic
  WHERE $__timeFilter(time) AND direction = ${direction:sqlstring}
), devices AS (
  SELECT device FROM selected LEFT JOIN device_labels d ON d.mac=selected.device
LEFT JOIN as_names a ON a.asn=selected.remote_as
GROUP BY device ORDER BY sum(bytes) DESC LIMIT LEAST(50, GREATEST(1, ${top:sqlstring}::int))
), ases AS (
  SELECT remote_as FROM selected LEFT JOIN device_labels d ON d.mac=selected.device
LEFT JOIN as_names a ON a.asn=selected.remote_as
GROUP BY remote_as ORDER BY sum(bytes) DESC LIMIT LEAST(50, GREATEST(1, ${top:sqlstring}::int))
), services AS (
  SELECT service FROM selected LEFT JOIN device_labels d ON d.mac=selected.device
LEFT JOIN as_names a ON a.asn=selected.remote_as
GROUP BY service ORDER BY sum(bytes) DESC LIMIT LEAST(50, GREATEST(1, ${top:sqlstring}::int))
)
SELECT CASE WHEN device IN (SELECT device FROM devices) THEN COALESCE(d.label, device::text) ELSE 'Other devices' END AS "Device",
       CASE WHEN remote_as IN (SELECT remote_as FROM ases) THEN COALESCE(a.name, 'AS' || remote_as::text) ELSE 'Other ASes' END AS "AS",
       CASE WHEN service IN (SELECT service FROM services) THEN service ELSE 'Other services' END AS "Service",
       sum(bytes)::double precision AS "Bytes"
FROM selected LEFT JOIN device_labels d ON d.mac=selected.device
LEFT JOIN as_names a ON a.asn=selected.remote_as
GROUP BY 1,2,3 ORDER BY 4 DESC
