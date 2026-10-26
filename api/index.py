"""api/index.py - Serverless WSGI entry point for Vercel deployment.

Vercel detects Python Serverless Functions in the api/ directory.
This module imports the Flask `app` object from the project root and
exposes it to Vercel's Python runtime.
"""

import os
import sys

# Ensure the project root directory is at the beginning of sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app  # noqa: E402

# Vercel WSGI entry point expects an application named `app`
