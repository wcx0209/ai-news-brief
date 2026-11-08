#!/usr/bin/env python3
"""Run one collection cycle for CI without starting the resident scheduler."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from log_config import setup_logging
from pipeline_runner import cleanup_old_articles, run_pipeline


if __name__ == "__main__":
    setup_logging(log_name="collector")
    run_pipeline()
    cleanup_old_articles()
