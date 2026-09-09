"""Puts files/app on sys.path so tests import the package like the container does."""
import os
import sys

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)
