#!/usr/bin/env python3
"""Diagnostic fp L shell-card wrapper; build and verify are offline only.

The maintained ordinary headless path is build_autorun.py --fpl-shell.
Trial command lines and artifacts remain compatible with the PONG card.
"""
from card_build import *  # retain the diagnostic API used by the trial tools


if __name__ == '__main__':
    main()
