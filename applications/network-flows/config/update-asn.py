import gzip
import ipaddress
import os
from pathlib import Path
import signal
import sys
import time
import urllib.request


def update(directory):
    temporary = directory / "networks.new"
    count = 0
    with temporary.open("w") as output:
        for family in (4, 6):
            url = f"https://iptoasn.com/data/ip2asn-v{family}.tsv.gz"
            request = urllib.request.Request(url, headers={"User-Agent": "chlorinate-network-flows"})
            with urllib.request.urlopen(request, timeout=120) as response:
                with gzip.GzipFile(fileobj=response) as data:
                    for line in data:
                        first, last, asn, *_ = line.decode().rstrip("\n").split("\t")
                        if int(asn) == 0:
                            continue
                        for prefix in ipaddress.summarize_address_range(
                            ipaddress.ip_address(first), ipaddress.ip_address(last)
                        ):
                            output.write(f"{int(asn)},{prefix}\n")
                            count += 1
    if count < 10000:
        raise ValueError(f"incomplete ASN database: {count} prefixes")
    temporary.replace(directory / "networks.lst")
    print(f"Updated {count} ASN prefixes", flush=True)


def main():
    directory = Path("/maps")
    if "--once" in sys.argv:
        update(directory)
        return
    delay = 86400
    while True:
        time.sleep(delay)
        try:
            update(directory)
            os.kill(int((directory / "sfacctd.pid").read_text()), signal.SIGUSR2)
            delay = 86400
        except Exception as error:
            delay = 300
            print(f"ASN refresh/reload failed; retrying in {delay}s: {error}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
