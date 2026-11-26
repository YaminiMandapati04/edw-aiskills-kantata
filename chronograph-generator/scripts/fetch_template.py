#!/usr/bin/env python3
"""Download the pinned Chronograph template from its Snowflake stage into assets/.

    python fetch_template.py [--connection default] [--force]

The template is a binary .xlsx, which a shared Cortex skill cannot carry, so it is kept on
@MCP_DB.MCP_SCHEMA.STG_CHRONOGRAPH_REPORT/template/chronograph_template.xlsx. This copies it to
assets/chronograph_template.xlsx (skipped when already present unless --force). build_chronograph.py calls
it when the file is missing and still checks the file against the map's template_sha256.
Exit codes: 0 present, 1 refused.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TEMPLATE = os.path.join(SKILL, "assets", "chronograph_template.xlsx")
STAGE_PATH = "@MCP_DB.MCP_SCHEMA.STG_CHRONOGRAPH_REPORT/template/chronograph_template.xlsx"


def fetch(connection="default", force=False):
    """Return the local template path, downloading it from the stage if needed. Raises RuntimeError on failure."""
    if os.path.exists(TEMPLATE) and not force:
        return TEMPLATE
    import snowflake.connector
    os.makedirs(os.path.dirname(TEMPLATE), exist_ok=True)
    tmp = tempfile.mkdtemp()
    try:
        con = snowflake.connector.connect(connection_name=connection)
        try:
            con.cursor().execute(f"GET '{STAGE_PATH}' 'file://{tmp}/'")
        finally:
            con.close()
        got = os.path.join(tmp, "chronograph_template.xlsx")
        if not os.path.exists(got):
            raise RuntimeError(f"{STAGE_PATH} was not found or not readable with this role")
        shutil.move(got, TEMPLATE)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"could not download {STAGE_PATH}: {exc}") from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return TEMPLATE


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--connection", default="default", help="connection name in ~/.snowflake/connections.toml")
    ap.add_argument("--force", action="store_true", help="download even if assets/ already has the template")
    a = ap.parse_args()
    try:
        path = fetch(a.connection, a.force)
    except RuntimeError as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, indent=2))
        return 1
    print(json.dumps({"status": "OK", "template": path}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
