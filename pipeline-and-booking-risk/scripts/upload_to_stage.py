#!/usr/bin/env python3
"""Upload finished report files to this skill's Snowflake internal stage.

    python upload_to_stage.py outputs/<file> [outputs/<file> ...] [--stage @DB.SCHEMA.STAGE]
                              [--subpath <folder>] [--connection default] [--warehouse <WH>]

Default stage: @MCP_DB.MCP_SCHEMA.STG_GTM_REPORT . Files are uploaded unchanged (no compression), overwriting a file of the
same name, then listed back from the stage to confirm. It never changes role or database. Connection is read from
~/.snowflake/connections.toml. Exit codes: 0 uploaded and confirmed, 1 refused or failed.
"""
import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
DEFAULT_STAGE = "@MCP_DB.MCP_SCHEMA.STG_GTM_REPORT"


def refuse(msg, **extra):
    print(json.dumps({"status": "REFUSED", "reason": msg, **extra}, indent=2, default=str))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--stage", default=DEFAULT_STAGE)
    ap.add_argument("--subpath", default="", help="optional folder inside the stage, e.g. 2026-10")
    ap.add_argument("--connection", default="default")
    ap.add_argument("--warehouse")
    a = ap.parse_args()
    if not a.stage.startswith("@") or any(c in a.stage for c in " ;'\""):
        refuse("--stage must be a plain @DB.SCHEMA.STAGE name", stage=a.stage)
    for f in a.files:
        if not os.path.isfile(f):
            refuse(f"{f} does not exist: build the report first")
    import snowflake.connector
    try:
        con = snowflake.connector.connect(connection_name=a.connection)
    except Exception as e:
        refuse(f"cannot connect to Snowflake: {e}")
    cur = con.cursor()
    if a.warehouse:
        cur.execute(f'USE WAREHOUSE "{a.warehouse}"')
    target = a.stage + ("/" + a.subpath.strip("/") if a.subpath.strip("/") else "")
    done = []
    try:
        for f in a.files:
            uri = os.path.abspath(f).replace("\\", "/")
            cur.execute(f"PUT 'file://{uri}' {target} AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
            done.append(os.path.basename(f))
        names = {r[0].split("/")[-1] for r in cur.execute(f"LIST {target}").fetchall()}
    except Exception as e:
        refuse(f"upload failed: {e}", uploaded=done)
    finally:
        con.close()
    missing = [n for n in done if n not in names]
    if missing:
        refuse("uploaded but not found on the stage", missing=missing, stage=target)
    print(json.dumps({"status": "UPLOADED", "stage": target, "files": done}, indent=2))


if __name__ == "__main__":
    main()
