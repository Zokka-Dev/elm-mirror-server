#!/usr/bin/env python3
"""
One-off script to backfill docs.json files for existing mirrored packages.

Usage:
    python backfill_docs.py [--mirror-content DIR] [--rate-limit N]
"""

import argparse
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

ELM_PACKAGE_SERVER = "https://package.elm-lang.org"
DEFAULT_RATE_LIMIT = 10_000  # requests per hour


def fetch_docs_json(author: str, name: str, version: str) -> list:
    """Fetch docs.json from the Elm package server."""
    url = f"{ELM_PACKAGE_SERVER}/packages/{author}/{name}/{version}/docs.json"
    request = urllib.request.Request(url, headers={"User-Agent": "elm-mirror-backfill/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Backfill docs.json for existing packages")
    parser.add_argument(
        "--mirror-content",
        type=str,
        default="mirror",
        help="Directory containing mirror content (default: mirror)"
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=DEFAULT_RATE_LIMIT,
        help=f"Maximum requests per hour (default: {DEFAULT_RATE_LIMIT})"
    )
    args = parser.parse_args()

    mirror_dir = Path(args.mirror_content).resolve()
    packages_dir = mirror_dir / "packages"

    if not packages_dir.exists():
        print(f"Error: packages directory not found at {packages_dir}")
        return 1

    # Calculate delay between requests
    delay = 3600.0 / args.rate_limit if args.rate_limit > 0 else 0

    # Find all package versions that need docs.json
    packages_to_update = []

    for author_dir in packages_dir.iterdir():
        if not author_dir.is_dir():
            continue
        for name_dir in author_dir.iterdir():
            if not name_dir.is_dir():
                continue
            for version_dir in name_dir.iterdir():
                if not version_dir.is_dir():
                    continue

                docs_path = version_dir / "docs.json"
                elm_json_path = version_dir / "elm.json"

                # Only update packages that have elm.json but no docs.json
                if elm_json_path.exists() and not docs_path.exists():
                    packages_to_update.append({
                        "author": author_dir.name,
                        "name": name_dir.name,
                        "version": version_dir.name,
                        "docs_path": docs_path
                    })

    print(f"Found {len(packages_to_update)} packages needing docs.json")

    if not packages_to_update:
        print("Nothing to do!")
        return 0

    success_count = 0
    fail_count = 0

    for i, pkg in enumerate(packages_to_update, 1):
        pkg_id = f"{pkg['author']}/{pkg['name']}@{pkg['version']}"
        print(f"[{i}/{len(packages_to_update)}] Fetching docs.json for {pkg_id}...")

        try:
            docs = fetch_docs_json(pkg["author"], pkg["name"], pkg["version"])
            with open(pkg["docs_path"], "w", encoding="utf-8") as f:
                json.dump(docs, f)
            success_count += 1
        except urllib.error.HTTPError as e:
            print(f"  Error: HTTP {e.code} - {e.reason}")
            fail_count += 1
        except Exception as e:
            print(f"  Error: {e}")
            fail_count += 1

        # Rate limiting
        if delay > 0 and i < len(packages_to_update):
            time.sleep(delay)

    print(f"\nComplete: {success_count} succeeded, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    exit(main())
