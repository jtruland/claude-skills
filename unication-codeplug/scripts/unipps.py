#!/usr/bin/env python3
"""Unpack / repack Unication GxPPS .unipps codeplug containers.

    unipps.py unpack <file.unipps> <dir>
    unipps.py pack   <dir> <file.unipps> [--restamp] [--pad-to=N]

Header (60 bytes), then the payload: a plain zip of SQLite 2.1 databases.

    0..3    FE FE FE FE       magic
    4..9    01 02 00 01 00 00 constant
    10..13  u32 big-endian    Unix epoch seconds, stamped when the file is written
    14..15  00 01             constant
    16..17  u16 big-endian    CRC of header[0..15]  ^ 0xBBBE   <- covers the timestamp
    18..21  u32 big-endian    36 + len(payload)   (high half is zero below 64 KiB)
    22..23  u16 big-endian    CRC of GUID + payload
    24..59  36 ASCII bytes    GUID, matches the main .db filename

Both CRCs are the same function: poly 0x1021, input bytes reflected, result reflected
once at the end, init 0x0000, xorout 0x0000.

Bytes 16..17 depend on the timestamp, so the two move together. Changing the timestamp
without recomputing this field produces a file GxPPS silently refuses - that is what
made several early test files fail. pack() always recomputes all three fields.
"""
import sys, os, io, json, time, zipfile, shutil

MAGIC = b'\xfe\xfe\xfe\xfe'
HDR_LEN = 60
B_CONST = 0xBBBE
_RB = [int(f'{i:08b}'[::-1], 2) for i in range(256)]
_TBL = []
for _b in range(256):
    _c = _b << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021) & 0xFFFF if _c & 0x8000 else (_c << 1) & 0xFFFF
    _TBL.append(_c)

def _rev16(x):
    return int(f'{x:016b}'[::-1], 2)

def crc(data, state=0):
    for byte in data:
        state = ((state << 8) & 0xFFFF) ^ _TBL[((state >> 8) ^ _RB[byte]) & 0xFF]
    return _rev16(state)

def fix_header(hdr, payload):
    """Recompute every derived field. hdr is a bytearray; bytes 10..13 must already
    hold the intended timestamp, since field 16..17 is computed over them."""
    hdr[16:18] = (crc(bytes(hdr[0:16])) ^ B_CONST).to_bytes(2, 'big')
    # bytes 18..21 as one big-endian u32. Every observed file has 18..19 == 00 00,
    # which is equally consistent with a 32-bit length whose high half is zero, so
    # this writes identical bytes for any payload under 64 KiB and only diverges above.
    ln = 36 + len(payload)
    if ln > 0xFFFFFFFF:
        sys.exit(f"payload too large even for a 32-bit length: {ln}")
    hdr[18:22] = ln.to_bytes(4, 'big')
    hdr[22:24] = crc(bytes(hdr[24:]) + payload).to_bytes(2, 'big')
    return hdr

def check(hdr, payload):
    want = fix_header(bytearray(hdr), payload)
    return [(n, bytes(hdr[a:b]), bytes(want[a:b]))
            for n, a, b in (('field16', 16, 18), ('length', 18, 22), ('crc', 22, 24))]

def unpack(src, outdir):
    raw = open(src, 'rb').read()
    if raw[:4] != MAGIC:
        sys.exit(f"not a .unipps container: magic is {raw[:4].hex()}, expected fefefefe")
    hdr, payload = raw[:HDR_LEN], raw[HDR_LEN:]
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, '_header.bin'), 'wb').write(hdr)
    open(os.path.join(outdir, '_payload.zip'), 'wb').write(payload)
    tree = os.path.join(outdir, 'tree')
    if os.path.isdir(tree):
        shutil.rmtree(tree)
    os.makedirs(tree)
    order = []
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for i in zf.infolist():
            order.append({'name': i.filename, 'date_time': list(i.date_time),
                          'compress_type': i.compress_type, 'is_dir': i.is_dir(),
                          'external_attr': i.external_attr, 'create_system': i.create_system})
            zf.extract(i, tree)
    json.dump({'guid': hdr[24:].decode(), 'members': order},
              open(os.path.join(outdir, '_manifest.json'), 'w'), indent=2)
    ts = int.from_bytes(hdr[10:14], 'big')
    print(f"unpacked -> {outdir}")
    print(f"  guid    {hdr[24:].decode()}")
    print(f"  written {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(ts))}")
    for n, got, want in check(hdr, payload):
        print(f"  {n:8s}{got.hex()} ({'ok' if got == want else 'BAD, expected ' + want.hex()})")
    for m in order:
        print(f"  member  {m['name']}")

def restamp_payload(tree, man, old_txt, new_txt):
    """Rewrite the save-time string inside the databases. Same length, so the SQLite
    files are structurally untouched and no sqlite binary is needed."""
    hits = 0
    for m in man['members']:
        if m['is_dir']:
            continue
        p = os.path.join(tree, m['name'])
        b = open(p, 'rb').read()
        n = b.count(old_txt.encode())
        if n:
            open(p, 'wb').write(b.replace(old_txt.encode(), new_txt.encode()))
            hits += n
    return hits

def build_payload(man, tree, pad_to=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for m in man['members']:
            zi = zipfile.ZipInfo(m['name'], date_time=tuple(m['date_time']))
            zi.compress_type = m['compress_type']
            zi.external_attr = m['external_attr']
            zi.create_system = m['create_system']
            if m['is_dir']:
                zf.writestr(zi, b'')
            else:
                zf.writestr(zi, open(os.path.join(tree, m['name']), 'rb').read())
        if pad_to is not None:
            pass
    payload = buf.getvalue()
    if pad_to is not None:
        need = pad_to - len(payload)
        if need < 0:
            sys.exit(f"cannot pad: payload is already {len(payload)} > {pad_to}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for m in man['members']:
                zi = zipfile.ZipInfo(m['name'], date_time=tuple(m['date_time']))
                zi.compress_type = m['compress_type']
                zi.external_attr = m['external_attr']
                zi.create_system = m['create_system']
                if m['is_dir']:
                    zf.writestr(zi, b'')
                else:
                    zf.writestr(zi, open(os.path.join(tree, m['name']), 'rb').read())
            zf.comment = b'\x00' * need
        payload = buf.getvalue()
    return payload

def pack(indir, dst, restamp=False, pad_to=None):
    hdr = bytearray(open(os.path.join(indir, '_header.bin'), 'rb').read())
    man = json.load(open(os.path.join(indir, '_manifest.json')))
    tree = os.path.join(indir, 'tree')
    if restamp:
        old_epoch = int.from_bytes(hdr[10:14], 'big')
        now = int(time.time())
        # the databases record the save a few seconds before the file is stamped
        old_txt = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(old_epoch - 7))
        new_txt = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now - 7))
        n = restamp_payload(tree, man, old_txt, new_txt)
        if n != 1:
            sys.exit(f"--restamp: expected exactly one {old_txt!r} in the payload, found {n}")
        print(f"restamped payload {old_txt} -> {new_txt}")
        hdr[10:14] = now.to_bytes(4, 'big')
    payload = build_payload(man, tree, pad_to)
    fix_header(hdr, payload)
    open(dst, 'wb').write(bytes(hdr) + payload)
    print(f"packed -> {dst} ({HDR_LEN + len(payload)} bytes)")
    print(f"  written {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(int.from_bytes(hdr[10:14],'big')))}")
    print(f"  field16 {hdr[16:20].hex()}   length {int.from_bytes(hdr[20:22],'big')}   crc {hdr[22:24].hex()}")

if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    flags = {x for x in sys.argv[1:] if x.startswith('--')}
    if len(a) != 3 or a[0] not in ('unpack', 'pack'):
        sys.exit(__doc__)
    if a[0] == 'unpack':
        unpack(a[1], a[2])
    else:
        pad = next((int(f.split('=')[1]) for f in flags if f.startswith('--pad-to=')), None)
        pack(a[1], a[2], restamp='--restamp' in flags, pad_to=pad)
