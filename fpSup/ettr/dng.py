"""Read-only LibRaw DNG adapter and explicit, non-overwriting sidecars."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .core import Exposure, MeterConfig, meter_raw


def rational(value):
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return float(value[0])/float(value[1])
    return float(value)


def crop_bounds(tags, height, width, top_margin=0, left_margin=0):
    """DNG DefaultCrop is relative to ActiveArea, in full-RAW coordinates.

    Use the exact DNG rectangle rather than LibRaw's even-aligned crop (which
    can drop a row); slice the CFA map identically so odd origins stay correct.
    """
    if 'DefaultCropOrigin' not in tags and 'DefaultCropSize' not in tags:
        return 0, 0, height, width
    if 'DefaultCropOrigin' not in tags or 'DefaultCropSize' not in tags:
        raise ValueError('incomplete DNG default crop')

    def pair(values):
        if len(values) == 4:
            values = (rational(values[:2]), rational(values[2:]))
        if len(values) != 2 or any(not float(v).is_integer() for v in values):
            raise ValueError('only integer-pixel DNG crops are supported')
        return tuple(int(v) for v in values)

    x, y = pair(tags['DefaultCropOrigin'])
    w, h = pair(tags['DefaultCropSize'])
    active = tags.get('ActiveArea', (top_margin, left_margin,
                                   top_margin+height, left_margin+width))
    if len(active) != 4 or x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ValueError('invalid DNG crop')
    if x+w > active[3]-active[1] or y+h > active[2]-active[0]:
        raise ValueError('DNG crop exceeds ActiveArea')
    x += active[1]-left_margin
    y += active[0]-top_margin
    if not (0 <= x < x+w <= width and 0 <= y < y+h <= height):
        raise ValueError('DNG crop exceeds LibRaw visible raster')
    return y, x, y+h, x+w


def analyze(path, config=MeterConfig()):
    import rawpy
    import tifffile

    path = Path(path)
    if path.suffix.lower() != '.dng':
        raise ValueError('DNG input required')
    exif, raw_tags = {}, {}
    with tifffile.TiffFile(path) as tiff:
        def visit(pages):
            for page in pages:
                yield page
                if page.pages:
                    yield from visit(page.pages)
        raw_pages = 0
        for page in visit(tiff.pages):
            tag = page.tags.get('ExifTag')
            if tag:
                exif.update(tag.value)
            if page.photometric == 32803:  # CFA
                raw_pages += 1
                for name in ('ActiveArea', 'DefaultCropOrigin', 'DefaultCropSize', 'BaselineExposure'):
                    if name in page.tags:
                        raw_tags[name] = page.tags[name].value
        if raw_pages != 1:
            raise ValueError('exactly one CFA RAW page required')
    with rawpy.imread(str(path)) as raw:
        if raw.raw_pattern is None or raw.raw_pattern.shape != (2, 2):
            raise ValueError('only 2x2 Bayer CFA DNG is supported')
        # LibRaw applies the DNG LinearizationTable during unpack. A TIFF
        # page.asarray() on fp L 8-bit CinemaDNG would meter companded codes.
        whites = raw.camera_white_level_per_channel or [raw.white_level]*4
        height, width = raw.raw_image_visible.shape
        y0, x0, y1, x1 = crop_bounds(raw_tags, height, width,
                                    raw.sizes.top_margin, raw.sizes.left_margin)
        meter = meter_raw(raw.raw_image_visible[y0:y1, x0:x1],
                          raw.raw_colors_visible[y0:y1, x0:x1],
                          raw.black_level_per_channel, whites, config)
        shape = [y1-y0, x1-x0]
        pattern = raw.raw_colors_visible[y0:y0+2, x0:x0+2].tolist()
    try:
        iso = exif['ISOSpeedRatings']
        if isinstance(iso, (tuple, list)):
            iso = iso[0]
        exposure = Exposure(rational(exif['ExposureTime']), float(iso),
                            rational(exif['FNumber']))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError(f'{path.name}: missing/invalid manual exposure EXIF') from error
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            digest.update(chunk)
    return dict(source=str(path.resolve()), sha256=digest.hexdigest(),
                shape=shape, cfa_pattern=pattern, exposure=asdict(exposure),
                crop_in_visible_raw=[y0, x0, y1, x1],
                baseline_exposure_ev=rational(raw_tags.get('BaselineExposure', 0)),
                levels_basis='LibRaw unpacked-domain levels; fractional DNG black levels may be rounded',
                exposure_basis='nominal EXIF; effective sensor timing is not verified',
                meter=asdict(meter)), meter, exposure


def xmp(correction_ev):
    # No filename interpolation; XML is a minimal standalone development hint.
    # The RAW-relative correction may need a developer baseline-exposure offset.
    from .core import finite
    finite(correction_ev, 'correction_ev')
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '  <rdf:Description rdf:about="" '
            'xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" '
            f'crs:Exposure2012="{correction_ev:+.6f}"/>\n'
            ' </rdf:RDF>\n</x:xmpmeta>\n')


def write_output(directory, report, include_xmp=False):
    """Own a fresh directory; never replace an existing sidecar or RAW file.

    Sequence-numbered names avoid collisions between identical basenames in
    different take directories. Source/hash association is in each JSON file.
    """
    directory = Path(directory)
    # Serialize all records before creating outputs, rejecting NaN/invalid XMP.
    files = [('report.json', json.dumps(report, indent=2, allow_nan=False)+'\n')]
    for i, record in enumerate(report['frames']):
        name = f'{i:06d}-{Path(record["source"]).stem}'
        files.append((name+'.ettr.json', json.dumps(record, indent=2, allow_nan=False)+'\n'))
        if include_xmp:
            files.append((name+'.xmp', xmp(record['deflicker']['correction_ev'])))
    directory.mkdir(parents=True, exist_ok=False)
    for name, text in files:
        with (directory/name).open('x', encoding='utf-8') as output:
            output.write(text)
