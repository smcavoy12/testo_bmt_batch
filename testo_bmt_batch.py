#!/usr/bin/env python3
"""
Batch Testo .BMT -> temperature CSV + 16-bit integer TIFF (for Agisoft Metashape).

Usage:
    python3 testo_bmt_batch.py INPUT_FOLDER [OUTPUT_FOLDER] [--kelvin] [--scale N]

For every .BMT file in INPUT_FOLDER this writes:
    <name>_temperatures.csv   plain-text grid, degrees C, 2 decimals (reference)
    <name>_temperatures.tif   single-band uint16 raster (Agisoft-friendly)

Integer encoding (default):
    pixel_value = round(temperature_C * scale)          scale defaults to 100
    temperature_C = pixel_value / scale                 -> recover real temps
So 22.71 C is stored as 2271. Divide by 100 to get degrees C back.

uint16 cannot hold negatives. A normal indoor scene is all positive, but this
camera measures down to -30 C, so a sub-zero capture would underflow. For cold
scenes pass --kelvin, which stores centi-Kelvin instead (always positive):
    pixel_value = round((temperature_C + 273.15) * scale)
    temperature_C = pixel_value / scale - 273.15
The exact reversal formula for each file is written into the TIFF description.

The radiometric block is located automatically and never hardcoded by offset.
"""
import sys, os, glob, struct, csv
import numpy as np
import tifffile

IR_W, IR_H = 160, 120          # radiometric grid for this camera family
N = IR_W * IR_H
KELVIN = 273.15


def find_bmps(data):
    offs, i = [], 0
    while True:
        j = data.find(b'BM', i)
        if j < 0:
            break
        if j + 6 <= len(data):
            sz = struct.unpack('<I', data[j + 2:j + 6])[0]
            if 50 < sz <= len(data):
                offs.append(j)
        i = j + 1
    return offs


def bmp_pixel_end(data, off):
    offbits = struct.unpack('<I', data[off + 10:off + 14])[0]
    w = struct.unpack('<i', data[off + 18:off + 22])[0]
    h = abs(struct.unpack('<i', data[off + 22:off + 26])[0])
    bpp = struct.unpack('<H', data[off + 28:off + 30])[0]
    return off + offbits + w * h * (bpp // 8)


def extract(path):
    """Return (temps[H,W] float32 in degC, byte offset of the array)."""
    data = open(path, 'rb').read()

    bmps = find_bmps(data)
    if not bmps:
        raise RuntimeError("no BMP block found - not a Testo BMT?")
    # Candidate regions: the gap after each embedded BMP's pixel data, up to
    # the next BMP (or EOF). Most files keep the radiometric block between the
    # thermal and visual BMPs, but some put it after the visual image.
    regions = []
    for k, b in enumerate(bmps):
        start = bmp_pixel_end(data, b)
        end = bmps[k + 1] if k + 1 < len(bmps) else len(data)
        if end - start >= N * 4:
            regions.append((start, end))
    if not regions:
        raise RuntimeError("radiometric block too small for %dx%d" % (IR_W, IR_H))

    best = None
    for gap_start, gap_end in regions:
        limit = (gap_end - gap_start) - N * 4
        for rel in range(0, limit + 1):
            off = gap_start + rel
            arr = np.frombuffer(data[off:off + N * 4], dtype='<f4')
            if not np.isfinite(arr).all():
                continue
            if arr.min() < -60 or arr.max() > 1000:
                continue
            if not (0.5 <= (arr.max() - arr.min()) <= 300):
                continue
            if np.any(arr == 0.0):
                continue
            grid = arr.reshape(IR_H, IR_W)
            rough = float(np.abs(np.diff(grid, axis=1)).sum() +
                          np.abs(np.diff(grid, axis=0)).sum())
            if best is None or rough < best[0]:
                best = (rough, off, grid)

    if best is None:
        raise RuntimeError("could not locate temperature array")
    _, off, temps = best                       # row 0 = top of image (top-down)
    return temps.astype(np.float32), off


def write_csv(temps, path):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        for row in temps:
            w.writerow(['%.2f' % v for v in row])


def to_uint16(temps, scale, kelvin):
    offset = KELVIN if kelvin else 0.0
    scaled = np.rint((temps + offset) * scale)
    if scaled.min() < 0:
        raise ValueError("negative values after scaling (min %.2f C); "
                         "re-run with --kelvin" % float(temps.min()))
    if scaled.max() > 65535:
        raise ValueError("values exceed uint16 range at scale=%g; lower --scale"
                         % scale)
    formula = ("degC = pixel/%g - %g" % (scale, KELVIN)) if kelvin \
              else ("degC = pixel/%g" % scale)
    return scaled.astype(np.uint16), offset, formula


def write_tiff(temps, path, scale, kelvin):
    u16, offset, formula = to_uint16(temps, scale, kelvin)
    desc = ("Testo BMT temperatures. %s. scale=%g offset=%g unit=%s"
            % (formula, scale, offset,
               "centi-Kelvin" if kelvin else "centi-degC"))
    tifffile.imwrite(path, u16, photometric='minisblack', description=desc)
    return formula


def main():
    args = sys.argv[1:]
    kelvin = '--kelvin' in args
    args = [a for a in args if a != '--kelvin']
    scale = 100.0
    if '--scale' in args:
        k = args.index('--scale')
        scale = float(args[k + 1]); del args[k:k + 2]
    if not args:
        print(__doc__); sys.exit(1)

    in_dir = args[0]
    out_dir = args[1] if len(args) > 1 else in_dir
    os.makedirs(out_dir, exist_ok=True)

    files = sorted({p for p in glob.glob(os.path.join(in_dir, '*'))
                    if p.lower().endswith('.bmt')})
    if not files:
        print("No .BMT files found in", in_dir); sys.exit(1)

    print("Integer encoding: scale=%g  mode=%s\n"
          % (scale, "centi-Kelvin (--kelvin)" if kelvin else "centi-degC"))
    ok = 0
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        csv_path = os.path.join(out_dir, stem + '_temperatures.csv')
        tif_path = os.path.join(out_dir, stem + '_temperatures.tif')
        try:
            temps, off = extract(path)
            write_csv(temps, csv_path)
            formula = write_tiff(temps, tif_path, scale, kelvin)
            print("OK  %-22s %.2f..%.2f degC  ->  %s"
                  % (os.path.basename(path), temps.min(), temps.max(), formula))
            ok += 1
        except Exception as e:
            print("FAIL %-22s %s" % (os.path.basename(path), e))

    print("\n%d/%d files processed -> %s" % (ok, len(files), out_dir))


if __name__ == '__main__':
    main()
