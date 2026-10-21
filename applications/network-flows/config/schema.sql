SELECT pg_advisory_lock(6343);

CREATE TABLE IF NOT EXISTS upload (
  mac_src macaddr NOT NULL, ip_src inet NOT NULL, ip_dst inet NOT NULL,
  as_dst bigint NOT NULL, port_dst integer NOT NULL, ip_proto smallint NOT NULL,
  packets bigint NOT NULL, bytes bigint NOT NULL,
  stamp_inserted timestamp without time zone NOT NULL,
  stamp_updated timestamp without time zone
);
CREATE TABLE IF NOT EXISTS download (
  mac_dst macaddr NOT NULL, ip_dst inet NOT NULL, ip_src inet NOT NULL,
  as_src bigint NOT NULL, port_src integer NOT NULL, ip_proto smallint NOT NULL,
  packets bigint NOT NULL, bytes bigint NOT NULL,
  stamp_inserted timestamp without time zone NOT NULL,
  stamp_updated timestamp without time zone
);
CREATE INDEX IF NOT EXISTS upload_time ON upload (stamp_inserted);
CREATE INDEX IF NOT EXISTS download_time ON download (stamp_inserted);

CREATE OR REPLACE FUNCTION is_external(remote_ip inet, local_ip inet)
RETURNS boolean LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
  SELECT CASE WHEN family(remote_ip) = 6 THEN
    remote_ip <<= '2000::/3'::inet
    AND NOT remote_ip <<= network(set_masklen(local_ip, 56))
  ELSE NOT remote_ip <<= ANY(ARRAY[
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16',
    '224.0.0.0/4', '240.0.0.0/4'
  ]::inet[]) END
$$;

CREATE OR REPLACE VIEW traffic AS
SELECT stamp_inserted AT TIME ZONE 'UTC' AS time,
       'upload'::text AS direction, mac_src AS device_mac, ip_src AS device_ip,
       as_dst AS remote_as, port_dst AS service_port, ip_proto, packets, bytes, ip_dst AS remote_ip
FROM upload WHERE is_external(ip_dst, ip_src)
UNION ALL
SELECT stamp_inserted AT TIME ZONE 'UTC', 'download', mac_dst, ip_dst,
       as_src, port_src, ip_proto, packets, bytes, ip_src
FROM download WHERE is_external(ip_src, ip_dst);

CREATE TABLE IF NOT EXISTS as_names (
  asn bigint PRIMARY KEY, name text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS device_names (
  mac macaddr PRIMARY KEY, name text, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS address_names (
  ip inet PRIMARY KEY, name text, expires_at timestamptz NOT NULL
);
CREATE OR REPLACE VIEW device_labels AS
SELECT mac, CASE WHEN name IS NULL OR updated_at < now() - interval '1 day' THEN mac::text
                WHEN count(*) OVER (PARTITION BY name) > 1 THEN name || ' (' || mac::text || ')'
                ELSE name END AS label
FROM device_names;

GRANT CONNECT ON DATABASE flows TO flow_reader;
GRANT USAGE ON SCHEMA public TO flow_reader;
GRANT SELECT ON traffic, as_names, device_labels, address_names TO flow_reader;

SELECT pg_advisory_unlock(6343);
