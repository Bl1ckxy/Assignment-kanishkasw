"""Central config: paths, DB settings, constants.

Password is NEVER stored here — scripts read os.environ["MYSQL_PWD"].
"""
import os
from pathlib import Path

# --- paths -----------------------------------------------------------------
ROOT = Path(r"H:\kanishka")
PROJECT = ROOT / "project"
SPLIT = ROOT / "split"
LOGS = PROJECT / "logs"
OUTPUTS = PROJECT / "outputs"
SQL_DIR = PROJECT / "sql"
VENV_PY = PROJECT / "venv" / "Scripts" / "python.exe"
MYSQL_EXE = r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"

# --- database --------------------------------------------------------------
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_NAME = "cafe"

# --- business constants ----------------------------------------------------
# FY 2024-25 in IST (inclusive start, exclusive end)
FY_START = "2024-04-01"
FY_END = "2025-04-01"
IST_OFFSET = "+05:30"          # analysis sessions display/derive in IST
UTC_OFFSET = "+00:00"          # import session used UTC (dump header)
# Columns compared before choosing the time base;
# the chosen canonical timestamp column is set AFTER the comparison run.
TZ_COMPARE_COLUMNS = ["order_date", "IST_timezone", "created_at"]


def require_password() -> str:
    """Fail loudly if MYSQL_PWD is missing instead of prompting/hardcoding."""
    pw = os.environ.get("MYSQL_PWD")
    if not pw:
        raise RuntimeError(
            "MYSQL_PWD is not set. Set it in the shell before running: "
            "setx MYSQL_PWD <password> (new shells) or $env:MYSQL_PWD=<password>"
        )
    return pw
