# Isolated conftest for client-only tests.
# This file intentionally does NOT import any server-side modules,
# so client tests can run without server dependencies installed.
#
# Run client tests with:
#   pytest tests/client/ --noconftest
# (--noconftest skips the parent tests/conftest.py which requires server deps)

import sys
import os

# Add client/ to sys.path so bare imports (e.g. `from config import ...`) work
# the same way they do when the app runs from the client/ directory on Android.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "client"))
