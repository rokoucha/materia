import gzip
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import dns.resolver
import psycopg
import enrich


class LookupTests(unittest.TestCase):
    def test_mac_alias_and_hostname(self):
        answer = [SimpleNamespace(target='laptop.home.arpa.')]
        fake = SimpleNamespace(resolve=lambda query, kind: ['172.16.1.100'] if kind == 'A' else answer)
        with patch.object(enrich, 'resolver', return_value=fake) as resolver:
            self.assertEqual(enrich.device_name('02:00:00:00:00:01'), 'laptop')
            resolver.assert_called_once_with(True)

    def test_missing_ptr_is_negative_cached(self):
        fake = SimpleNamespace(resolve=lambda *args: (_ for _ in ()).throw(dns.resolver.NXDOMAIN()))
        with patch.object(enrich, 'resolver', return_value=fake):
            self.assertEqual(enrich.reverse_name('1.1.1.1'), (None, 3600))
            self.assertIsNone(enrich.device_name('02:00:00:00:00:01'))

    def test_positive_ptr_ttl_bounded(self):
        class Answer(list):
            rrset = SimpleNamespace(ttl=1)
        fake = SimpleNamespace(resolve=lambda *args: Answer([SimpleNamespace(target='one.one.one.one.')]))
        with patch.object(enrich, 'resolver', return_value=fake):
            self.assertEqual(enrich.reverse_name('1.1.1.1'), ('one.one.one.one', 300))


class DatabaseTests(unittest.TestCase):
    def test_metadata_labels_and_totals(self):
        with psycopg.connect(autocommit=True) as db:
            before = db.execute('SELECT count(*),sum(bytes) FROM traffic').fetchone()
            with patch.object(enrich, 'device_name', return_value='laptop'), patch.object(enrich, 'reverse_name', return_value=('test.example', 300)) as reverse:
                enrich.update_dns(db)
                called = reverse.call_count
                self.assertGreater(called, 0)
                enrich.update_dns(db)
                self.assertEqual(reverse.call_count, called)
            self.assertEqual(db.execute('SELECT DISTINCT label FROM device_labels').fetchall(), [('laptop',)])
            rows = [f'1.0.0.0\t1.0.0.255\t{asn}\tUS\tOrganization {asn}\n' for asn in range(1, 10002)]
            compressed = gzip.compress(''.join(rows).encode())
            with patch.object(enrich.urllib.request, 'urlopen', side_effect=lambda *a, **kw: io.BytesIO(compressed)) as request:
                enrich.update_as_names(db)
                self.assertEqual(request.call_count, 2)
                enrich.update_as_names(db)
                self.assertEqual(request.call_count, 2)
            self.assertEqual(db.execute('SELECT name FROM as_names WHERE asn=1').fetchone()[0], 'Organization 1')
            db.execute("INSERT INTO as_names(asn,name) VALUES (13335,'Cloudflare') ON CONFLICT(asn) DO UPDATE SET name=excluded.name")
            after = db.execute('''SELECT count(*),sum(bytes) FROM traffic t
                LEFT JOIN device_labels d ON d.mac=t.device_mac
                LEFT JOIN as_names a ON a.asn=t.remote_as
                LEFT JOIN address_names n ON n.ip=t.remote_ip''').fetchone()
            self.assertEqual(before, after)
            sql = Path('/queries/sankey.sql').read_text()
            sql = sql.replace('$__timeFilter(time)', "time > now() - interval '1 day'").replace('${direction:sqlstring}', "'download'").replace('${top:sqlstring}', "'20'").replace('${device:sqlstring}', "'all'")
            rows = db.execute(sql).fetchall()
            self.assertEqual(sum(row[3] for row in rows), 200000)
            self.assertEqual(rows[0][:2], ('laptop', 'Cloudflare'))
            dashboard = json.loads(Path('/dashboard/network-flows.json').read_text())
            panels = dashboard['panels'] + [p for row in dashboard['panels'] for p in row.get('panels', [])]
            for selected_device in ('all', '02:00:00:00:00:01', '02:00:00:00:00:ff'):
                for panel in panels:
                    for target in panel.get('targets', []):
                        if 'rawSql' not in target:
                            continue
                        sql = target['rawSql']
                        sql = re.sub(r"\$__timeFilter\(([^)]+)\)", r"\1 > now() - interval '1 day'", sql)
                        sql = re.sub(r"\$__timeGroupAlias\(time,'5m',0\)", 'to_timestamp(floor(extract(epoch from time)/300)*300) AS "time"', sql)
                        for key, value in [('direction', 'download'), ('top', '10'), ('device', selected_device)]:
                            sql = sql.replace('${' + key + ':sqlstring}', "'" + value + "'")
                        with self.subTest(panel=panel['title'], device=selected_device):
                            result = db.execute(sql).fetchall()
                            if panel['id']==3:
                                expected = 0 if selected_device.endswith(':ff') else 200000
                                self.assertEqual(sum(row[3] for row in result), expected)
            self.assertEqual(db.execute('SELECT count(*) FROM traffic WHERE remote_ip IS NOT NULL').fetchone()[0], 5)
            db.execute("UPDATE device_names SET updated_at=now()-interval '2 days'")
            self.assertEqual(db.execute('SELECT bool_and(label=mac::text) FROM device_labels').fetchone()[0], True)


if __name__ == '__main__':
    unittest.main()
