"""Send synthetic sFlow v5 samples to an isolated collector, never production."""
import ipaddress
import socket
import struct
import sys


def words(*values):
    return struct.pack("!" + "I" * len(values), *values)


def sample(sequence, source, destination, upload=True, routed=True):
    router = bytes.fromhex("00e0b46c8087")
    device = bytes.fromhex("020000000001")
    src = router if not upload else device
    dst = router if upload else device
    if not routed:
        dst = bytes.fromhex("020000000002")
    source, destination = map(ipaddress.ip_address, (source, destination))
    sport, dport = (50000, 443) if upload else (443, 50000)
    udp = struct.pack("!HHHH", sport, dport, 8, 0)
    if source.version == 4:
        ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 28, 0, 0, 64, 17, 0, source.packed, destination.packed)
        protocol = b"\x08\x00"
    else:
        ip = struct.pack("!IHBB16s16s", 6 << 28, 8, 17, 64, source.packed, destination.packed)
        protocol = b"\x86\xdd"
    header = dst + src + protocol + ip + udp
    raw = words(1, 1000, 4, len(header)) + header
    raw += b"\0" * (-len(raw) % 4)
    record = words(1, len(raw)) + raw
    flow = words(sequence, 10, 100, sequence * 100, 0, 10 if upload else 0, 0 if upload else 10, 1) + record
    return words(5, 1) + socket.inet_aton("172.16.1.1") + words(0, sequence, 1000, 1, 1, len(flow)) + flow


def main():
    target = sys.argv[1]
    if "--empty" in sys.argv:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(words(5, 1) + socket.inet_aton("172.16.1.1") + words(0, 100, 1000, 0), (target, 6343))
        return
    cases = [
        ("172.16.1.100", "1.1.1.1", True, True),
        ("1.1.1.1", "172.16.1.100", False, True),
        ("240b:10:1234:5601::100", "2606:4700:4700::1111", True, True),
        ("2606:4700:4700::1111", "240b:10:1234:5601::100", False, True),
        ("172.16.1.100", "172.16.2.21", True, True),
        ("240b:10:1234:5601::100", "240b:10:1234:5602::21", True, True),
        ("172.16.1.100", "1.1.1.1", True, False),
        ("240b:10:abcd:1201::100", "2606:4700:4700::1111", True, True),
    ]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for sequence, case in enumerate(cases, 1):
            sock.sendto(sample(sequence, *case), (target, 6343))


if __name__ == "__main__":
    main()
