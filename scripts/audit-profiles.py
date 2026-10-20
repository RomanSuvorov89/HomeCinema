#!/usr/bin/env python3
"""Read-only inventory before migrating an existing installation to user profiles."""
import argparse
import json
from pathlib import Path
import sqlite3


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def inspect(path):
    result = {"file": path.name, "tables": []}
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for (name,) in tables:
                columns = [row[1] for row in connection.execute("PRAGMA table_info(" + quoted(name) + ")")]
                profile = next((column for column in columns if column.lower() in
                                {"profile_id", "profileid", "profile", "account_id", "accountid"}), None)
                table = {"table": name}
                try:
                    table["rows"] = connection.execute("SELECT COUNT(*) FROM " + quoted(name)).fetchone()[0]
                    if profile:
                        table["profile_column"] = profile
                        table["by_profile"] = [
                            {"id": str(key) if key is not None else None, "rows": count}
                            for key, count in connection.execute(
                                "SELECT " + quoted(profile) + ",COUNT(*) FROM " + quoted(name)
                                + " GROUP BY " + quoted(profile) + " LIMIT 50")
                        ]
                except sqlite3.Error as error:
                    table["error"] = str(error)
                result["tables"].append(table)
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as error:
        result["error"] = str(error)
    return result


def databases(directory):
    if not directory.is_dir():
        return {"error": "Directory is missing", "databases": []}
    paths = sorted(path for path in directory.iterdir()
                   if path.is_file() and path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".sql"})
    return {"databases": [inspect(path) for path in paths]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--lampac-database", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "version": 1,
        "catalog": databases(args.catalog),
        "lampac": databases(args.lampac_database),
        "note": "Counts and profile IDs only. Client-only history and settings are not included.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
