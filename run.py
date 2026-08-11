"""
Single documented entry point. Builds the clean db if it doesn't exist yet,
then launches the dashboard. Freight and competitor-price data are separate
optional steps (they need two other local servers running) -- see README.

Run: python run.py
"""
import os
import subprocess
import sys

import config

if __name__ == "__main__":
    if not os.path.exists(config.DB_PATH):
        print(f"ERROR: {config.DB_PATH} not found.")
        print("Copy the supplied kestrel_ops.db there first (see README) -- it is not committed to this repo.")
        sys.exit(1)

    if not os.path.exists(config.CLEAN_DB_PATH):
        print("Building cleaned database (first run only)...")
        subprocess.run([sys.executable, "etl/build_clean_db.py"], check=True)

    subprocess.run([sys.executable, "-m", "streamlit", "run", "app/app.py"], check=True)
