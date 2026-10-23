"""Explicit firmware targets for the incremental fp L port.

The C headers are the single source of loader entry-point addresses. This
module selects them; it does not infer offsets or supply fp scratch as an fp L
fallback. Image fingerprints are offline provenance checks, never BIN/AutoRun
pairing or a camera-side firmware hash requirement.
"""
from dataclasses import dataclass
import hashlib
import pathlib

@dataclass(frozen=True)
class Camera:
    name: str
    define: int
    main_size: int
    main_sha256: str
    card_supported: bool

    def loader_defines(self):
        return [f'FPSUP_CAMERA={self.define}']

    def require_card_support(self):
        if not self.card_supported:
            raise ValueError(
                f'{self.name}: generic product-card packaging is not supported yet. '
                 'The diagnostic shell card and RAM/card transfers are camera-proven; '
                'ordinary headless packaging requires build_autorun.py --fpl-shell '
                'with its explicit restricted flags and verified --main image. '
                'Use the fp L development workflow, not fp product/Fast/UI builds. '
                'See docs/FPL_PORT.md and docs/FPL_TOOLS.md.')

    def verify_main(self, image):
        data = pathlib.Path(image).read_bytes()
        if len(data) != self.main_size or hashlib.sha256(data).hexdigest() != self.main_sha256:
            raise ValueError(f'{self.name}: not the inspected declared-length MAIN image')
        return data


DEFAULT_CAMERA = 'fp-5.02'
CAMERAS = {
    'fp-5.02': Camera('fp-5.02', 502, 49245696,
                     'aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622', True),
    'fp-l-3.02': Camera('fp-l-3.02', 10302, 49310208,
                       'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9', False),
}


def get_camera(name=DEFAULT_CAMERA):
    try:
        return CAMERAS[name]
    except KeyError:
        raise ValueError(f'unknown camera firmware {name!r}; choose {", ".join(CAMERAS)}') from None
