#!/usr/bin/env python3
"""fpSup-Merge v3: build the merge page for Loader v3 cards.

    python3 tools/merge-v3/build_catalogue_v3.py          writes tools/merge-v3/index.html

A Loader v3 card is a folder, not one BIN (projects/usb-shell-sup/notes/LOADER_V3.md):

    AutoRun.txt          identical in every v3 release
    fpSup/LOADER.BIN     identical in every v3 release
    fpSup/UI/0..4.BIN    identical in every v3 release
    fpSup/NNNAME.BIN     one per product; the loader loads them in name order

so merging is copying the products' fpSup/ folders together.  Nothing is
relocated or patched, and a sup whose claims collide with an earlier one
releases itself at boot without writing a firmware word.  The page still
refuses the pairs that would only ever end that way (EXCL below).

This builder reads the newest frozen v3 release of every product in PRODUCTS,
checks each file against its MANIFEST.txt, refuses if the shared files differ
between the releases it picked (ignoring only historical AutoRun filler),
and embeds the bytes in template.html. The
page re-hashes every file of the zip against these hashes before it offers
the download. Historical AutoRun filler is removed after manifest verification,
before comparing shared commands. Released files on disk are never rewritten.
Final Instant/Fast boot pairs are rebuilt from the maintained shared builder;
product and data files retain their manifest-verified release bytes. The Res
tools may instead come from a separately verified development snapshot.
"""
import argparse, base64, datetime, hashlib, json, pathlib, re, struct, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent.parent
RELEASES = FPSUP / 'releases'
TEMPLATE = HERE / 'template.html'
GUIDE = FPSUP / 'guide'
OUT = HERE / 'index.html'
SITE_COPY = HERE.parent / 'card-composer' / 'index.html'
# Res-Custom is a versioned release; do not override it with a development snapshot.
INPUTS = [HERE / 'inputs' / name for name in ('stopfx-20261012', 'fcap-20261015')]
sys.path.insert(0, str(FPSUP / 'fp_usb_shell'))
from autorun_text import without_legacy_padding
from v3 import build_v3 as V3
from release_history import attach_history

SHARED = ['AutoRun.txt', 'fpSup/LOADER.BIN'] + [f'fpSup/UI/{i}.BIN' for i in range(5)]
SUP_RE = re.compile(r'^[0-9]{2}.+\.BIN$')

# product -> page metadata. Development Res tools are separate manifest-checked
# snapshots; frozen releases are never rewritten to add virtual RCD support.
#
# category: the page's sections, in CATEGORIES order.
# excl: pairs whose claims collide.  Symmetric (checked below).  The page still
#   lets both onto the card -- the one not chosen goes on as fpSup/NAME.OFF,
#   which the loader (it lists *.BIN only) skips; renaming .OFF <-> .BIN
#   switches which one runs (user 2026-10-07).
# summary: the tile's one line -- what it does, never how to use it or its
#   caveats (user 2026-10-07); those live on the guide page behind the link.
# author / credits: shown on the tile and written into the card's README.
#   author is left empty for the site's own sups (user 2026-10-07: they are
#   mine, no need to say so); set it only for a sup someone else wrote.
#   credits are people whose work the sup builds on, not its authors.  Keep
#   them in step with the guide page's "Thank you" box (test checks it).
CATEGORIES = ['format', 'focus', 'motion', 'monitor', 'development']
# the page shows sups in this order (user 2026-10-07); the card's load order is
# still the file names'
ORDER = ['res-custom', 'res-lab', 'lossless', 'fcap', 'unlocked-writer', 'stopfx', 'split-record', 'hdrx', 'af', 'gyro2', 'raw-view', 'screenflip', 'desqueeze', 'tap-to-zoom', 'lut', 'usbshell']
AUTHOR = ''
PRODUCTS = {
    # og3k / og2k: not this round (user 2026-10-07) -- the OG line ships as
    # res-custom.  Their v3 drafts in releases/ are not to be offered.
    # res-custom carries data files in fpSup/RESCUS/ (one .RCD per format); the
    # user picks which go on the card.  Its excl names products not on this page
    # (old OG cards, Jose's 31FMT, res-lab): kept so the list is complete when
    # one of them is added.  Preliminary -- sigmafp-re-70, 2026-10-07.
    'res-custom': dict(name='Res-Custom',
                       summary=dict(en='Custom recording resolutions in one sup: open gate OG2K, OG3K, OG3.5K, OG4K and S16.',
                                    zh='多種自訂錄影解析度合一:Open Gate OG2K、OG3K、OG3.5K、OG4K 與 S16。'), category='format', file='32RESCUS.BIN',
                       excl=['og3k', 'og2k', 'formats'],
                       data=dict(dir='RESCUS', ext='.RCD',
                                 names={'OG35K': 'OG3.5K'},
                                 # per-format author shown on its chip (user 2026-10-13)
                                 authors={k: 'Jose Hurtado' for k in ('OG35K', 'OG4K', 'S16')},
                                 # chip order on the page (user 2026-10-13); others after, by name
                                 order=['OG2K', 'OG3K', 'OG35K', 'OG4K', 'S16']),
                       author=AUTHOR, credits=['Jose Hurtado'],
                       pending=True),
    'res-lab': dict(name='RES-Lab', category='format', file='50RES-Lab v0.1.0test.BIN',
                    excl=[], requires=['res-custom'], needs_manager=True, stage='dev', pending=True,
                    summary=dict(en='Adjust the sensor readout, crop and recording size with a live diagram, and save custom formats.',
                                 zh='搭配示意圖調整感光元件讀取方式、裁切與錄影尺寸，並可保存自訂格式。'),
                    author=AUTHOR, credits=[]),
    # links: ticking this tile also ticks those (user 2026-10-15: Lossless
    # ticks FCAP -- without it a compressed take stops at ~94 frames, the
    # stock batch waiting for 128 files -- but FCAP can still be unticked;
    # unlike requires, which RES-Lab uses for Res-Custom and which holds).
    'lossless':   dict(name='Lossless',
                       summary=dict(en='Record smaller CinemaDNG files with lossless compression, preserving image quality.',
                                    zh='錄製容量更小、畫質不變的無損壓縮 CinemaDNG。'), category='format', excl=[],
                       links=['fcap'], author=AUTHOR, credits=['CorNy']),
    # projects/rec-core/fcap: the stock writer sends a batch of files at 64 MiB
    # or 128 files; FCAP makes it 40 files, so small (compressed) frames never
    # fill the 96-slot descriptor pool. Full-size RAW batches still close at
    # 64 MiB first and are unchanged.
    'fcap':       dict(name='FCAP', sup_id='FCAP', file='30FCAP.BIN',
                       summary=dict(en='Writes small frames to the card sooner, so long compressed or small-format takes do not stop early. Needed by Lossless.',
                                    zh='讓小幀更早寫入記憶卡，壓縮或小尺寸格式的長錄影不會提早停止。Lossless 需要它。'),
                       category='format', excl=[], author=AUTHOR, credits=[]),
    # projects/rec-core/writer: the stock batch write, sent by our own task
    # without the FS lock (SD and SSD alike).  No links: whether Lossless
    # should tick it is the user's call (lossless-sup, 2026-10-15).
    'unlocked-writer': dict(name='Unlocked Writer', sup_id='ULWR', file='20ULWR.BIN',
                       summary=dict(en='Writes recordings to the SD card or SSD without holding the file-system lock, so the camera keeps working while the card is written. SD card: on by itself (Video Speed Class and CMD20 are detected). SSD: works only with Write Mode turned on.',
                                    zh='寫卡時不握檔案系統鎖，寫入 SD 卡或 SSD 的同時，相機照常處理後續畫格。SD 卡自動生效(自動辨識 Video Speed Class 與 CMD20);SSD 要開啟 Write Mode 才會生效。'),
                       category='format', excl=[], author=AUTHOR, credits=[]),
    'stopfx':     dict(name='STOPFX', sup_id='STFX', file='05STOPFX.BIN',
                       summary=dict(en='Helps the camera clear pending frames after an abnormal recording stop. Use alone or with Lossless.',
                                    zh='幫助相機在異常停錄後清理暫存影格，可單獨或搭配 Lossless 使用。'),
                       category='format', excl=[], author='Ruari', credits=[]),
    'raw-view':   dict(name='RAW-View',
                       summary=dict(en='The screen shows the RAW about to be recorded: what clips on screen clips in the DNG.',
                                    zh='螢幕顯示即將錄下的 RAW:畫面上過曝的地方，錄下來就是過曝。'), category='monitor', excl=[], author=AUTHOR, credits=['Ole Berek', 'Luka']),
    'screenflip': dict(name='ScreenFlip',
                       summary=dict(en='Flip the rear screen 180°, mirror it, or both.',
                                    zh='背螢幕翻轉 180°、左右鏡像，或兩者。'), category='monitor', excl=[], author=AUTHOR, credits=[]),
    # Jose Hurtado's original Loader v3 releases, kept byte-for-byte.
    'desqueeze': dict(name='Desqueeze', category='monitor', excl=[],
                      summary=dict(en='Anamorphic preview at 1.33x, 1.6x or 2.0x, with scaled frame guides and an amber indicator. Recorded files are unchanged.',
                                   zh='變形鏡頭預覽以 1.33x、1.6x 或 2.0x 還原比例，構圖線跟著縮放並顯示琥珀色標記；錄下的檔案不變。'),
                      author='Jose Hurtado', credits=[]),
    'tap-to-zoom': dict(name='Tap to Zoom', category='monitor', excl=[],
                        summary=dict(en='Tap the LCD to zoom around that point; dials select 2x, 4x or 8x and the next tap restores the full frame. Works while recording.',
                                     zh='輕觸 LCD，以該點為中心放大；轉盤可選 2x、4x 或 8x，再點一次還原全畫面。錄影中也可使用。'),
                        author='Jose Hurtado', credits=[]),
    'gyro2':      dict(name='Gyro2',
                       summary=dict(en='Gyro data inside every CinemaDNG frame; stabilise in DaVinci Resolve with the Gyroflow plugin (fpSup build).',
                                    zh='把陀螺儀資料寫進每一格 CinemaDNG,用 Gyroflow 的 DaVinci Resolve 插件(fpSup 版)防震。'), category='motion', excl=[], file='40GYR2.BIN',
                       author=AUTHOR, credits=[],
                       pending=True),
    # In development (user 2026-10-07: show what is coming).  stage='dev' tiles
    # are greyed and say so; they have no release and cannot be ticked.
    'split-record': dict(name='Split Record', category='format', excl=[], stage='dev', pending=True,
                       summary=dict(en='Records CinemaDNG to the SD card and an SSD at once, splitting the frames between them.',
                                    zh='CinemaDNG 同時寫進 SD 卡與 SSD,把畫格分流到兩邊。'),
                       author=AUTHOR, credits=[]),
    'hdrx':       dict(name='HDRx', category='format', excl=[], stage='dev', pending=True,
                       summary=dict(en='Records alternating normal and short exposures, merged in post for a wider dynamic range.',
                                    zh='交替錄下正常與短曝光的畫格，後製合成更寬的動態範圍。'),
                       author=AUTHOR, credits=[]),
    # projects/fp-af-assist; stage 'long' = long-term development
    'af':         dict(name='AF Optimisation', category='focus', excl=[], stage='long', pending=True,
                       summary=dict(en='Better in-camera continuous autofocus while recording in CINE.',
                                    zh='改善 CINE 錄影時的機內連續自動對焦。'),
                       author=AUTHOR, credits=[]),
    'lut':        dict(name='LUT', category='monitor', excl=[], stage='dev', pending=True,
                       summary=dict(en='Load a .cube LUT and see its look simulated on the screen; recorded files are unchanged.',
                                    zh='讀取 .cube LUT,在螢幕上模擬還原調色後的樣子;錄下的檔案不變。'),
                       author=AUTHOR, credits=[]),
    'usbshell':   dict(name='Shell',
                       summary=dict(en='A development tool: commands and memory access to the camera over USB.',
                                    zh='開發工具：透過 USB 對相機下指令、讀寫記憶體。'), category='development', excl=[], author=AUTHOR, credits=[]),
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def embedded(files):
    return [dict(path=rel, size=len(b), sha256=sha(b), data=base64.b64encode(b).decode())
            for rel, b in files.items()]


def boot_options(shared):
    """Frozen products stay exact; final boot packaging comes from the shared
    builder. Every choice embeds a complete, independently hashed pair."""
    for i, pixels in enumerate(V3.splash_frames()):
        if shared[f'fpSup/UI/{i}.BIN'] != pixels:
            raise SystemExit('released splash differs from the current shared boot artwork')
    variants = {}
    for manager in (False, True):
        for instant in (False, True):
            for fast in (False, True):
                ar, loader, info = V3.boot_card(instant=instant, fast=fast, allsups=manager)
                key = ('m1' if manager else '') + f'i{int(instant)}f{int(fast)}'
                variants[key] = dict(info=dict(info, manager=manager), files=embedded({'AutoRun.txt': ar, 'fpSup/LOADER.BIN': loader}))
    sys.path.insert(0, str(FPSUP / 'uishare/tab'))
    import build_ft6
    management, _ = build_ft6.data_file()
    default = variants['i1f0']['files']
    ui = embedded({rel: shared[rel] for rel in SHARED[2:]})
    sources = [FPSUP / 'fp_usb_shell' / p for p in
               ['build_autorun.py', 'firmware.py', 'asm/loader.S', 'asm/stage2.S', 'asm/store_boot.S',
                 'asm/abort.S', 'asm/splash_finish.S', 'v3/build_v3.py', 'v3/sloader_entry.S', 'v3/sloader.c', 'v3/allsups.c']]
    sources += sorted((FPSUP / 'fp_usb_shell/firmware').glob('*.h'))
    sources += list((FPSUP / 'uishare/tab').glob('*.py'))
    sources += list((FPSUP / 'uishare').glob('*.c')) + list((FPSUP / 'uishare').glob('*.h'))
    return default + ui, dict(default=dict(instant=True, fast=False, manager=False), variants=variants,
                             manager_files=embedded({'fpSup/UI/ALLSUPS.BIN': management}),
                             sources={str(p.relative_to(FPSUP)): sha(p.read_bytes()) for p in sources})


def input_products(directory):
    """Read exact development snapshots; require every recorded file hash.
    They are selectable builds, not a published version or a release rewrite.
    """
    if directory is None:
        return []
    meta = json.loads((directory / 'manifest.json').read_text())
    verified = {}
    for rel, expected in meta['files'].items():
        if pathlib.PurePosixPath(rel).is_absolute() or '..' in pathlib.PurePosixPath(rel).parts:
            raise SystemExit('invalid snapshot path: ' + rel)
        b = (directory / rel).read_bytes()
        if len(b) != expected['size'] or sha(b) != expected['sha256']:
            raise SystemExit('snapshot does not match manifest: ' + rel)
        verified[rel] = b
    def sup_file(rel, expected_sid):
        b = verified[rel]
        magic, hlen, flen, block, entry, sid, version, service = struct.unpack_from('<8I', b)
        if (magic != V3.SL_MAGIC or hlen != 32 or flen != len(b) or block < flen or
                not 32 <= (entry & ~1) < flen or sid.to_bytes(4, 'little') != expected_sid.encode() or service > V3.SL_SVC_VERSION):
            raise SystemExit('invalid snapshot sup: ' + rel)
        return dict(size=len(b), sha256=sha(b), data=base64.b64encode(b).decode()), version
    out = []
    for key, entry in meta['products'].items():
        spec = PRODUCTS[key]
        if spec.get('stage') in ('dev', 'long'):
            continue
        payload, version = sup_file(entry['file'], spec.get('sup_id', 'RLAB' if key == 'res-lab' else 'RCUS'))
        filename = pathlib.PurePosixPath(entry['file'])
        p = dict(id=key, name=filename.stem.lstrip('0123456789') if key == 'res-lab' else spec['name'], category=spec['category'], file=filename.name,
                 excl=list(spec['excl']), requires=spec.get('requires', []), links=spec.get('links', []), needs_manager=spec.get('needs_manager', False),
                 author=spec['author'], credits=spec['credits'], release=entry.get('release', f'fpsup-{key}-dev-r{version}'),
                 version=str(version),
                 build_label=entry.get('build_label', dict(en='Development build', zh='開發版')), date=meta['date'], about=spec['summary'], guide=guide(key),
                 provenance=dict(manifest=str(directory.relative_to(HERE) / 'manifest.json') if directory.is_relative_to(HERE) else str(directory / 'manifest.json'),
                                 source_sha256=meta['source_sha256']), data_files=[], support_files=[], **payload)
        for rel in entry.get('data_files', []):
            b = verified[rel]
            target = 'fpSup/RESCUS/' + pathlib.PurePosixPath(rel).name
            p['data_files'].append(dict(label=label(spec, target), author=data_author(spec, target), **embedded({target:b})[0]))
        for rel in entry.get('support_files', []):
            target = 'fpSup/RESCUS/' + pathlib.PurePosixPath(rel).name
            p['support_files'] += embedded({target:verified[rel]})
        p['data_files'].sort(key=lambda d: data_rank(spec, d['path']))
        if entry.get('virtual'):
            p['virtual'], _ = sup_file(entry['virtual'], 'RCUS')
        out.append(p)
    return out


def version_key(q):
    """Same ordering as card-composer: numbers as numbers, then plain >
    one-letter revision > word suffix."""
    nums = tuple(int(n) for n in re.findall(r'\d+', q))
    tail = re.sub(r'^[\d.]*', '', q)
    return (nums, 2 if not tail else (1 if len(tail) == 1 else 0), tail)


def version_of(d):
    return re.split(r'-v(?=\d)', d.name, maxsplit=1)[1]


def latest_v3(product):
    """Newest fpsup-<product>-v*/ that is a v3 card (has fpSup/LOADER.BIN).
    Drafts (_draft-*) never match the glob."""
    found = [(version_key(version_of(d)), d) for d in RELEASES.glob(f'fpsup-{product}-v*')
             if d.is_dir() and (d / 'fpSup' / 'LOADER.BIN').is_file()]
    return max(found)[1] if found else None


def manifest(d):
    """{path: sha256} from MANIFEST.txt."""
    out = {}
    for line in (d / 'MANIFEST.txt').read_text(encoding='utf-8').splitlines():
        m = re.match(r'^(\S+)\s+[\d,]+B\s+sha256=([0-9a-f]{64})$', line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def updated(d, sup):
    """The release's date, YYYY-MM-DD: the last commit touching its folder,
    or -- while it is not committed yet -- the sup file's mtime.  (A fresh
    checkout resets mtimes, so the commit date wins whenever there is one.)"""
    try:
        out = subprocess.run(['git', 'log', '-1', '--format=%cs', '--', '.'], cwd=d,
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ''
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', out):
        return out
    return datetime.date.fromtimestamp((d / 'fpSup' / sup).stat().st_mtime).isoformat()


def label(spec, rel):
    stem = pathlib.PurePosixPath(rel).stem
    return spec['data'].get('names', {}).get(stem, stem)


def data_rank(spec, rel):
    order, stem = spec['data'].get('order', []), pathlib.PurePosixPath(rel).stem
    return (order.index(stem) if stem in order else len(order), rel)


def data_author(spec, rel):
    return spec['data'].get('authors', {}).get(pathlib.PurePosixPath(rel).stem, '')


def guide(key):
    """The tile's details are the site's illustrated guide page, nothing else
    (user 2026-10-07: no README text on the page).  '' when it has none yet."""
    return f'../../guide/{key}.html' if (GUIDE / f'{key}.html').exists() else ''


def load(product, d, spec):
    """(sup name, {path: bytes}, [data file paths]).  A product's data files
    live in fpSup/<dir>/ and are optional per file."""
    sups = [p for p in (d / 'fpSup').iterdir() if p.is_file() and SUP_RE.match(p.name)]
    if len(sups) != 1:
        raise SystemExit(f'{d.name}: expected one NNNAME.BIN in fpSup/, found {[p.name for p in sups]}')
    sup = sups[0]
    man = manifest(d)
    files = {}
    for rel in SHARED + [f'fpSup/{sup.name}']:
        b = (d / rel).read_bytes()
        if man.get(rel) != sha(b):
            raise SystemExit(f'{d.name}/{rel}: sha256 does not match MANIFEST.txt')
        files[rel] = b
    if files[f'fpSup/{sup.name}'][:4] != b'FSB1':
        raise SystemExit(f'{d.name}/{sup.name}: not an FSB1 sup')
    data = []
    if spec.get('data'):
        sub = d / 'fpSup' / spec['data']['dir']
        for f in sorted(sub.glob('*' + spec['data']['ext'])) if sub.is_dir() else []:
            rel = str(f.relative_to(d))
            b = f.read_bytes()
            if man.get(rel) != sha(b):
                raise SystemExit(f'{d.name}/{rel}: sha256 does not match MANIFEST.txt')
            files[rel] = b
            data.append(rel)
        if not data:
            raise SystemExit(f'{d.name}: no {spec["data"]["ext"]} in fpSup/{spec["data"]["dir"]}/')
    extra = sorted(str(p.relative_to(d)) for p in (d / 'fpSup').rglob('*')
                   if p.is_file() and str(p.relative_to(d)) not in files)
    if extra:
        raise SystemExit(f'{d.name}: files in fpSup/ this page would drop: {extra}')
    return sup.name, files, data


def main():
    global RELEASES, OUT
    ap = argparse.ArgumentParser()
    ap.add_argument('--releases', type=pathlib.Path, help='read releases from here (tests)')
    ap.add_argument('--out', type=pathlib.Path)
    ap.add_argument('--inputs', type=pathlib.Path, action='append', help='manifest-checked snapshot (repeat for separate products)')
    a = ap.parse_args()
    RELEASES = a.releases or RELEASES
    OUT = a.out or OUT
    inputs = a.inputs if a.inputs is not None else (INPUTS if not a.releases else [])
    for k, spec in PRODUCTS.items():
        if k not in ORDER:
            raise SystemExit(f'{k}: not in ORDER')
        if not (spec.get('summary', {}).get('en') and spec['summary'].get('zh')):
            raise SystemExit(f'{k}: needs summary en + zh')
        for o in spec['excl']:
            if o in PRODUCTS and k not in PRODUCTS[o]['excl']:
                raise SystemExit(f'excl not symmetric: {k} -> {o}')

    products, shared, skipped, pending = [], None, [], []
    for key, spec in PRODUCTS.items():
        d = None if spec.get('stage') in ('dev', 'long') else latest_v3(key)
        if d is None:
            skipped.append(key)
            # shown greyed out, not selectable: the user wants to see what is coming
            if spec.get('pending'):
                pending.append(dict(id=key, name=spec['name'], category=spec['category'],
                                    file=spec.get('file', ''), author=spec['author'],
                                    credits=list(spec['credits']), about=spec['summary'],
                                    stage=spec.get('stage', 'unreleased'),
                                    guide=guide(key)))
            continue
        sup, files, data = load(key, d, spec)
        common = {rel: files[rel] for rel in SHARED}
        common['AutoRun.txt'] = without_legacy_padding(common['AutoRun.txt'])
        if shared is None:
            shared, shared_from = common, d.name
        else:
            diff = [rel for rel in SHARED if sha(common[rel]) != sha(shared[rel])]
            if diff:
                raise SystemExit(f'{d.name} and {shared_from} differ in {diff}: '
                                 'rebuild the older release on the current loader first')
        b = files[f'fpSup/{sup}']
        if spec['category'] not in CATEGORIES:
            raise SystemExit(f'{key}: category {spec["category"]!r} not in CATEGORIES')
        products.append(dict(id=key, name=spec['name'], category=spec['category'],
                             excl=list(spec['excl']), links=spec.get('links', []), author=spec['author'],
                             credits=list(spec['credits']), release=d.name,
                             version=version_of(d), date=updated(d, sup),
                             file=sup, size=len(b), sha256=sha(b),
                             about=spec['summary'], data=base64.b64encode(b).decode(),
                             guide=guide(key),
                             data_files=[dict(path=rel, label=label(spec, rel), author=data_author(spec, rel), size=len(files[rel]),
                                              sha256=sha(files[rel]),
                                              data=base64.b64encode(files[rel]).decode())
                                         for rel in sorted(data, key=lambda r: data_rank(spec, r))]))
    if not products:
        raise SystemExit('no v3 release found')
    for p in [p for directory in inputs for p in input_products(directory)]:
        products = [q for q in products if q['id'] != p['id']] + [p]
        pending = [q for q in pending if q['id'] != p['id']]
        skipped = [q for q in skipped if q != p['id']]

    # Simplified Chinese = the Traditional text through the site's own character
    # table (assets/lang.js), so there is still only one Chinese text to keep.
    lj = (FPSUP / 'assets' / 'lang.js').read_text(encoding='utf-8')
    body = lj[lj.index('var MAP = {'):lj.index('};', lj.index('var MAP = {'))]
    t2s = dict(re.findall(r'"(.)":"(.)"', body))
    if len(t2s) < 500:
        raise SystemExit(f'assets/lang.js: only {len(t2s)} characters in MAP')
    boot_shared, boot = boot_options(shared)
    cat = dict(categories=CATEGORIES, t2s=t2s, shared=boot_shared, boot=boot,
               products=sorted(products, key=lambda p: p['file']),
               pending=sorted(pending, key=lambda p: p['file']),
               order=ORDER)
    attach_history(cat, RELEASES)
    page = TEMPLATE.read_text(encoding='utf-8')
    if page.count('@@CATALOGUE@@') != 1:
        raise SystemExit('template.html must hold @@CATALOGUE@@ exactly once')
    # </script> cannot occur in base64 or in the ABOUT text we embed, but guard anyway.
    blob = json.dumps(cat, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    rendered = page.replace('@@CATALOGUE@@', blob)
    OUT.write_text(rendered, encoding='utf-8')
    if not a.out:
        SITE_COPY.write_text(rendered, encoding='utf-8')

    print(f'wrote {OUT} ({OUT.stat().st_size:,} B)')
    for p in cat['products']:
        print(f"  {p['file']:<12} {p['release']:<36} {p['size']:>7,} B  {p['sha256'][:12]}")
    noguide = [p['id'] for p in cat['products'] + cat['pending'] if not p['guide']]
    if noguide:
        print('  no guide page (fpSup/guide/<id>.html) yet:', ', '.join(noguide))
    if skipped:
        print('  no v3 release yet:', ', '.join(skipped))
    print(f"  shared files from {shared_from}: " + ' '.join(sha(shared[r])[:8] for r in SHARED))


if __name__ == '__main__':
    main()
