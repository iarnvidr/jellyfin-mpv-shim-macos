"""Read-only PNG/state summary; crop equality is evidence, not OCR."""
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path


def menu_pixels(path):
    data = path.read_bytes()
    width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', data[16:29])
    assert depth == 8 and color in (2, 6) and interlace == 0, (path, depth, color, interlace)
    channels = 4 if color == 6 else 3
    compressed = bytearray()
    offset = 8
    while offset < len(data):
        size = struct.unpack('>I', data[offset:offset + 4])[0]
        if data[offset + 4:offset + 8] == b'IDAT':
            compressed.extend(data[offset + 8:offset + 8 + size])
        offset += size + 12
    raw = zlib.decompress(compressed)
    stride = width * channels
    previous = bytearray(stride)
    crop = bytearray()
    for y in range(min(24, height)):
        begin = y * (stride + 1)
        kind = raw[begin]
        row = bytearray(raw[begin + 1:begin + 1 + stride])
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            up = previous[x]
            upper_left = previous[x - channels] if x >= channels else 0
            if kind == 0:
                prediction = 0
            elif kind == 1:
                prediction = left
            elif kind == 2:
                prediction = up
            elif kind == 3:
                prediction = (left + up) // 2
            elif kind == 4:
                p = left + up - upper_left
                distance = (abs(p - left), abs(p - up), abs(p - upper_left))
                prediction = (left, up, upper_left)[distance.index(min(distance))]
            else:
                raise ValueError((path, kind))
            row[x] = (row[x] + prediction) & 255
        for x in range(min(750, width)):
            crop.extend(row[x * channels:x * channels + 3])
        previous = row
    return bytes(crop)


for folder in sys.argv[1:]:
    root = Path(folder)
    candidates = list(root.glob('original-*-playing-windowed.png'))
    if not candidates:
        continue
    baseline = menu_pixels(sorted(candidates)[0])
    rows = []
    for path in sorted(root.glob('*.json')):
        if not any(term in path.stem for term in ('stable', 'after-real-login', 'before-zoom')):
            continue
        state = json.loads(path.read_text())
        if 'mpvState' not in state:
            continue
        pixels = menu_pixels(path.with_suffix('.png'))
        rows.append({'capture': path.stem, 'os': state.get('macOSVersion'),
                     'mpvFullscreen': state['mpvState']['fullscreen'],
                     'axFullscreen': [window.get('AXFullScreen') for window in state['jellyfinAXWindows']],
                     'frontmost': state['frontmost'].get('bundle'),
                     'cropEqualWindowedBaseline': pixels == baseline,
                     'cropBlack': not any(pixels),
                     'cropSha256': hashlib.sha256(pixels).hexdigest()})
    print(json.dumps({'folder': folder, 'crop': [0, 0, 750, 24],
                      'baseline': str(sorted(candidates)[0]), 'states': rows}, indent=2))
