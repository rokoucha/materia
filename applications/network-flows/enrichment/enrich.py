import concurrent.futures
from datetime import datetime, timedelta, timezone
import gzip
import ipaddress
import os
import time
import urllib.request

import dns.exception
import dns.resolver
import dns.reversename
import psycopg


LOCAL_DNS = os.environ.get("LOCAL_DNS", "172.16.2.1")


def resolver(local=False):
    result = dns.resolver.Resolver(configure=not local)
    if local:
        result.nameservers = [LOCAL_DNS]
    result.timeout = 1
    result.lifetime = 2
    return result


def device_name(mac):
    query = f"mac-{mac.replace(':', '')}.devices.home.arpa"
    try:
        local = resolver(True)
        address = str(local.resolve(query, "A")[0])
        name = str(local.resolve(dns.reversename.from_address(address), "PTR")[0].target).rstrip(".")
        if name.endswith(".home.arpa") and not name.startswith("mac-"):
            return name.removesuffix(".home.arpa")
        return None
    except dns.exception.DNSException:
        return None


def reverse_name(address):
    try:
        local = ipaddress.ip_address(address) in ipaddress.ip_network("172.16.1.0/24")
        answer = resolver(local).resolve(dns.reversename.from_address(address), "PTR")
        return str(answer[0].target).rstrip("."), max(300, min(answer.rrset.ttl, 86400))
    except dns.exception.DNSException:
        return None, 3600


def update_as_names(db):
    stale = db.execute("SELECT NOT EXISTS (SELECT 1 FROM as_names WHERE updated_at > now() - interval '1 day')").fetchone()[0]
    if not stale:
        return
    names = {}
    for family in (4, 6):
        request = urllib.request.Request(f"https://iptoasn.com/data/ip2asn-v{family}.tsv.gz",
                                         headers={"User-Agent": "chlorinate-network-flows"})
        with urllib.request.urlopen(request, timeout=120) as response, gzip.GzipFile(fileobj=response) as data:
            for line in data:
                _, _, asn, _, name = line.decode().rstrip("\n").split("\t", 4)
                if int(asn) and name and name != "Not routed":
                    names[int(asn)] = name
    if len(names) < 10000:
        raise ValueError("Incomplete AS name download")
    with db.transaction():
        with db.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO as_names (asn, name) VALUES (%s, %s)
                ON CONFLICT (asn) DO UPDATE SET name=excluded.name, updated_at=now()
            """, sorted(names.items()))
    print(f"Updated {len(names)} AS names", flush=True)


def update_dns(db):
    devices = db.execute("""
        SELECT DISTINCT device_mac::text FROM traffic
        WHERE time > now() - interval '1 day'
    """).fetchall()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        names = list(pool.map(device_name, [row[0] for row in devices]))
    with db.transaction(), db.cursor() as cursor:
        cursor.executemany("""
            INSERT INTO device_names (mac, name) VALUES (%s, %s)
            ON CONFLICT (mac) DO UPDATE SET name=excluded.name, updated_at=now()
        """, [(row[0], name) for row, name in zip(devices, names)])
    addresses = db.execute("""
        WITH recent AS (
            SELECT device_ip AS ip, bytes FROM traffic WHERE time > now() - interval '1 hour'
            UNION ALL
            SELECT remote_ip, bytes FROM traffic WHERE time > now() - interval '1 hour'
        )
        SELECT host(r.ip) FROM recent r LEFT JOIN address_names n ON n.ip=r.ip
        WHERE n.ip IS NULL OR n.expires_at <= now()
        GROUP BY r.ip ORDER BY sum(bytes) DESC LIMIT 500
    """).fetchall()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        names = list(pool.map(reverse_name, [row[0] for row in addresses]))
    now = datetime.now(timezone.utc)
    with db.transaction(), db.cursor() as cursor:
        cursor.executemany("""
            INSERT INTO address_names (ip, name, expires_at) VALUES (%s, %s, %s)
            ON CONFLICT (ip) DO UPDATE SET name=excluded.name, expires_at=excluded.expires_at
        """, [(row[0], name, now + timedelta(seconds=ttl)) for row, (name, ttl) in zip(addresses, names)])
        cursor.execute("DELETE FROM address_names WHERE expires_at < now() - interval '7 days'")
        cursor.execute("DELETE FROM device_names WHERE updated_at < now() - interval '7 days'")
    print(f"Refreshed {len(devices)} devices and {len(addresses)} PTR records", flush=True)


def main():
    while True:
        try:
            with psycopg.connect(autocommit=True, connect_timeout=10, options="-c statement_timeout=30000") as db:
                try:
                    update_as_names(db)
                except Exception as error:
                    print(f"AS names refresh failed: {error}", flush=True)
                update_dns(db)
        except Exception as error:
            print(f"Metadata refresh failed: {error}", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    main()
