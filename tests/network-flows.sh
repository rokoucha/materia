#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
name="network-flows-test-$$"
config="$(mktemp -d)"
cleanup() {
  if [[ "$?" != 0 ]]; then
    docker logs "$name-collector" 2>&1 | tail -40 || true
    docker exec "$name-db" psql -U flows -d flows -c 'SELECT direction,remote_as,sum(bytes) FROM traffic GROUP BY 1,2' || true
  fi
  docker rm -f "$name-collector" "$name-db" >/dev/null 2>&1 || true
  docker network rm "$name" >/dev/null 2>&1 || true
  rm -rf "$config"
}
trap cleanup EXIT
mkdir -p "$config/maps"
chmod 755 "$config"
chmod 777 "$config/maps"
cp "$root/applications/network-flows/config/direction.map" "$config/"
python3 - "$root" "$config" <<'PY'
from pathlib import Path
import sys
root, target = map(Path, sys.argv[1:])
s = (root / 'applications/network-flows/config/sfacctd.conf').read_text()
s = s.replace('sql_refresh_time: 60', 'sql_refresh_time: 2') + '\nsql_passwd: disposable-test\n'
(target / 'sfacctd.conf').write_text(s)
import re
image = re.search(r'image: (pmacct/sfacctd:[^\s]+)', (root / 'applications/network-flows/resources/deployment.yaml').read_text()).group(1)
(target / 'image').write_text(image)
(target / 'maps/networks.lst').write_text('13335,1.1.1.0/24\n13335,2606:4700::/32\n')
PY
collector_image="$(cat "$config/image")"
docker network create "$name" >/dev/null
docker run -d --name "$name-db" --network "$name" --network-alias postgresql-rw \
  -e POSTGRES_PASSWORD=disposable-test -e POSTGRES_DB=flows -e POSTGRES_USER=flows postgres:18.1 >/dev/null
for _ in {1..60}; do
  if docker exec "$name-db" pg_isready -h 127.0.0.1 -U flows -d flows >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$name-db" psql -U flows -d flows -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE flow_reader LOGIN PASSWORD 'disposable-reader';" >/dev/null
docker exec -i "$name-db" psql -U flows -d flows -v ON_ERROR_STOP=1 \
  < "$root/applications/network-flows/config/schema.sql" >/dev/null
docker run -d --name "$name-collector" --network "$name" --network-alias collector \
  --user 10001:10001 --cap-drop ALL --security-opt=no-new-privileges \
  -v "$config:/etc/pmacct:ro" -v "$config/maps:/maps" "$collector_image" >/dev/null
for _ in {1..30}; do
  if docker logs "$name-collector" 2>&1 | grep -q 'waiting for sFlow'; then break; fi
  sleep 1
done
docker run --rm --network "$name" -v "$root/tests/network_flows_packets.py:/packets.py:ro" \
  python:3.14.0-slim-bookworm python /packets.py collector
for _ in {1..30}; do
  actual="$(docker exec "$name-db" psql -U flows -d flows -Atc \
    'SELECT count(*),sum(bytes),sum(packets) FROM traffic')"
  if [[ "$actual" == '5|500000|500' ]]; then break; fi
  sleep 1
done
[[ "$actual" == '5|500000|500' ]]
docker exec "$name-db" psql -U flows -d flows -v ON_ERROR_STOP=1 -c "
DO \$\$ BEGIN
  ASSERT (SELECT sum(bytes) FROM traffic WHERE direction='upload') = 300000;
  ASSERT (SELECT sum(bytes) FROM traffic WHERE direction='download') = 200000;
  ASSERT NOT EXISTS (SELECT 1 FROM traffic WHERE remote_as<>13335 OR service_port<>443);
  ASSERT NOT is_external('240b:10:1234:5602::21','240b:10:1234:5601::100');
  ASSERT is_external('2606:4700:4700::1111','240b:10:abcd:1201::100');
END \$\$;" >/dev/null
docker exec -e PGPASSWORD=disposable-reader "$name-db" \
  psql -h localhost -U flow_reader -d flows -Atc 'SELECT count(*) FROM traffic' | grep -qx 5
if docker exec -e PGPASSWORD=disposable-reader "$name-db" \
  psql -h localhost -U flow_reader -d flows -v ON_ERROR_STOP=1 -c 'DELETE FROM upload' >/dev/null 2>&1; then
  echo 'Reader unexpectedly has write access' >&2
  exit 1
fi
printf '64512,1.1.1.0/24\n64512,2606:4700::/32\n' > "$config/maps/networks.lst"
loaded="$(docker logs "$name-collector" 2>&1 | grep -Fc '[/maps/networks.lst] map successfully')"
docker kill --signal USR2 "$name-collector" >/dev/null
docker run --rm --network "$name" -v "$root/tests/network_flows_packets.py:/packets.py:ro" \
  python:3.14.0-slim-bookworm python /packets.py collector --empty
for _ in {1..30}; do
  reloaded="$(docker logs "$name-collector" 2>&1 | grep -Fc '[/maps/networks.lst] map successfully')"
  if (( reloaded >= loaded + 3 )); then break; fi
  sleep 1
done
(( reloaded >= loaded + 3 ))
docker run --rm --network "$name" -v "$root/tests/network_flows_packets.py:/packets.py:ro" \
  python:3.14.0-slim-bookworm python /packets.py collector
for _ in {1..30}; do
  updated="$(docker exec "$name-db" psql -U flows -d flows -Atc \
    'SELECT sum(bytes) FROM traffic WHERE remote_as=64512')"
  if [[ "$updated" == '500000' ]]; then break; fi
  sleep 1
done
[[ "$updated" == '500000' ]]
echo 'IPv4/IPv6, directions, PD changes, exclusions, normalization, reader permissions and ASN hot reload passed'
