"""Human-readable IDs reserved atomically in a ledger transaction."""
import sqlite3

ID_PREFIXES = frozenset({
    "PROJECT", "SRC", "EVID", "HYP", "HREV", "EXP", "ERREV", "RES",
    "READY", "IMPL", "CREV", "RUN", "ANALYSIS", "DEC", "EVENT", "COST",
    "CAND", "METRIC", "FEAS", "APKT", "PPLAN", "MANIFEST",
})


def reserve_id(connection: sqlite3.Connection, prefix: str) -> str:
    """Caller must own a transaction; counters survive process restarts."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"Unknown ID prefix: {prefix}")
    if not connection.in_transaction:
        raise RuntimeError("ID reservation requires an active transaction.")
    row = connection.execute(
        "INSERT INTO id_counters(prefix, value) VALUES (?, 1) "
        "ON CONFLICT(prefix) DO UPDATE SET value = value + 1 RETURNING value",
        (prefix,),
    ).fetchone()
    return f"{prefix}_{row[0]:04d}"
