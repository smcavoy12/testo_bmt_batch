# testo_bmt_batch

Batch-convert Testo `.BMT` thermograms into open, full-precision formats: a plain-text temperature grid (CSV) and a single-band 16-bit integer TIFF that photogrammetry software such as Agisoft Metashape can use directly.

Testo's `.BMT` files are proprietary and are normally only readable in Testo's own software. This script reads the radiometric temperature array straight out of each file. The original `.BMT` files are left untouched, so you can archive them next to the open outputs.

A companion Metashape script, `copy_jpg_pose_to_tiff.py`, copies camera poses from already-aligned thermal JPG exports onto the converted TIFFs. This lets the temperature rasters be used for texturing without aligning them again.

## Requirements

- Python 3.8+
- [NumPy](https://numpy.org/)
- [tifffile](https://pypi.org/project/tifffile/)

```bash
pip install numpy tifffile
```

## Usage

```bash
python3 testo_bmt_batch.py INPUT_FOLDER [OUTPUT_FOLDER] [--kelvin] [--scale N]
```

| Argument | Description |
| --- | --- |
| `INPUT_FOLDER` | Folder containing `.BMT` files (case-insensitive extension). |
| `OUTPUT_FOLDER` | Where outputs are written. Defaults to `INPUT_FOLDER`. |
| `--kelvin` | Store centi-Kelvin instead of centi-degrees Celsius (needed for scenes below 0 °C). |
| `--scale N` | Integer scale factor. Default `100`, i.e. 0.01 °C resolution. |

Example:

```bash
python3 testo_bmt_batch.py ./bmt ./converted
```

```
Integer encoding: scale=100  mode=centi-degC

OK  IV_00620.BMT           11.99..13.87 degC  ->  degC = pixel/100
OK  IV_00621.BMT           12.47..14.36 degC  ->  degC = pixel/100
...
61/61 files processed -> ./converted
```

Each file gets an `OK` or `FAIL` line, and a summary count is printed at the end. A file that fails does not stop the batch.

## Outputs

For every `<n>.BMT` the script writes:

| File | Contents |
| --- | --- |
| `<n>_temperatures.csv` | 160 × 120 grid of temperatures in °C, two decimals, row 0 = top of image. Human-readable reference. |
| `<n>_temperatures.tif` | Single-band `uint16` raster, 160 × 120, `minisblack`. |

### Integer encoding

`uint16` cannot hold fractions or negatives, so temperatures are scaled before storage.

| Mode | Stored value | Recover °C |
| --- | --- | --- |
| Default | `round(T_C × scale)` | `pixel / scale` |
| `--kelvin` | `round((T_C + 273.15) × scale)` | `pixel / scale − 273.15` |

With the default scale of 100, 22.71 °C is stored as `2271`. The exact formula used for each file is written into the TIFF's `ImageDescription` tag, so every file documents how to decode itself:

```
Testo BMT temperatures. degC = pixel/100. scale=100 offset=0 unit=centi-degC
```

The script refuses to write values that would overflow. A negative result asks you to rerun with `--kelvin`, and a value above 65535 asks for a lower `--scale`.

## How the radiometric data is located

A `.BMT` file contains embedded BMP images (a thermal preview and a visible-light image) plus a block of little-endian `float32` temperatures. The script never relies on a fixed byte offset. Instead it:

1. finds every embedded BMP by its `BM` header and computes where its pixel data ends;
2. treats the gap after each BMP, up to the next BMP or the end of the file, as a candidate region;
3. slides a 160 × 120 `float32` window through each region and keeps windows whose values are finite, non-zero, physically plausible (−60 to 1000 °C) and span 0.5–300 °C;
4. picks the spatially smoothest candidate, since real thermograms are smooth while misaligned reads look like noise.

Most files store the temperature block between the thermal and visible BMPs, but some store it after the visible image. Searching every gap handles both layouts.

## Using the TIFFs in Agisoft Metashape

The 16-bit TIFFs load into Metashape like any other image. Thermal images often align poorly on their own, though. If you already have aligned thermal JPG exports with the same filenames (`IV_00621.jpg` ↔ `IV_00621_temperatures.tif`), you can reuse their poses:

1. Add the converted TIFFs to the same chunk as the aligned JPGs.
2. In Metashape Pro, choose **Tools → Run Script…** and select `copy_jpg_pose_to_tiff.py`.

The script:

- matches cameras by filename stem, so the different extensions don't matter;
- copies each JPG camera's transform onto its TIFF;
- creates a TIFF sensor whose calibration is the JPG calibration rescaled to the TIFF resolution, and fixes it;
- disables the JPG cameras (set `DISABLE_JPGS = False` to keep them);
- reports any TIFFs with no matching or unaligned JPG.

This assumes the JPGs show the same thermal view as the TIFFs, only at a different resolution. Poses from visible-light images will not line up correctly because that camera has a different position and field of view.

## Limitations

- The radiometric grid is fixed at 160 × 120 (`IR_W`, `IR_H` at the top of the script). Cameras with other sensor sizes need those values changed.
- The format was worked out from sample files, not from a published specification. Check the outputs against Testo's software for a few files before relying on a new camera model or firmware.
- Temperatures are read exactly as the camera computed them. Emissivity and reflected temperature are not recalculated.

## Example dataset

This tool was used to prepare the thermographic survey of the Nymphaeum of Egeria (Rome), published on OpenHeritage3D: [doi:10.34946/D6C31M](https://doi.org/10.34946/D6C31M).

## License

MIT. See [LICENSE](LICENSE).
