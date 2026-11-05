"""Classify session failures without persisting credentials, paths or SQL values."""
import sqlite3
from pathlib import Path
from core.session_schema import SessionSchemaError


def session_error_code(error):
    cause = getattr(error, "orig", error)
    if isinstance(cause, SessionSchemaError):
        return "reauthorization_required"
    if isinstance(cause, sqlite3.Error):
        text = str(cause).lower()
        for markers, code in (
            (("database is locked", "database table is locked"), "sqlite_locked"),
            (("no such column", "no such table", "duplicate column name", "already exists"), "sqlite_schema"),
            (("unable to open database",), "sqlite_open"),
            (("readonly", "read-only"), "sqlite_readonly"),
            (("disk is full", "database or disk is full"), "sqlite_full"),
            (("malformed", "file is not a database"), "sqlite_corrupt"),
        ):
            if any(marker in text for marker in markers):
                return code
    return type(cause).__name__


def failure_location(error):
    trace = error.__traceback__
    if trace is None:
        return "unknown"
    while trace.tb_next is not None:
        trace = trace.tb_next
    return f"{Path(trace.tb_frame.f_code.co_filename).name}:{trace.tb_frame.f_code.co_name}:{trace.tb_lineno}"
