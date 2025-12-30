#!/usr/bin/env python3
"""
Script to split the mirror directory into chunks for GitHub releases.

GitHub releases have a 2GB file size limit, so this script splits the mirror
into chunks no larger than 2GB each, ensuring packages are not split across chunks.

Metadata files (all-packages, registry.json) are placed in their own separate chunk.
"""

import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


# Maximum chunk size in bytes (2GB with some margin for safety)
MAX_CHUNK_SIZE = 2 * 1024 * 1024 * 1024 - 100 * 1024 * 1024  # 1.9GB to be safe


def get_dir_size(path: Path) -> int:
    """Get the total size of a directory in bytes."""
    total = 0
    for entry in path.rglob('*'):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def get_file_size(path: Path) -> int:
    """Get the size of a file in bytes."""
    return path.stat().st_size if path.is_file() else 0


def get_packages_with_sizes(packages_dir: Path) -> List[Tuple[str, int]]:
    """
    Get all packages (author/package-name) with their total sizes.

    Returns a list of tuples: (package_path_relative, size_in_bytes)
    where package_path_relative is like "elm/core" or "mdgriffith/elm-ui"
    """
    packages = []

    # Iterate over authors
    for author_dir in sorted(packages_dir.iterdir()):
        if not author_dir.is_dir():
            continue

        author = author_dir.name

        # Iterate over packages by this author
        for package_dir in sorted(author_dir.iterdir()):
            if not package_dir.is_dir():
                continue

            package_name = package_dir.name
            package_path = f"{author}/{package_name}"
            package_size = get_dir_size(package_dir)
            packages.append((package_path, package_size))

    return packages


def create_chunks(packages: List[Tuple[str, int]], max_size: int) -> List[List[str]]:
    """
    Distribute packages into chunks, each no larger than max_size.

    Uses a simple first-fit decreasing algorithm for bin packing.
    """
    # Sort packages by size descending for better packing
    sorted_packages = sorted(packages, key=lambda x: x[1], reverse=True)

    chunks: List[List[str]] = []
    chunk_sizes: List[int] = []

    for package_path, package_size in sorted_packages:
        # Check if package itself is too large (shouldn't happen, but be safe)
        if package_size > max_size:
            print(f"Warning: Package {package_path} ({package_size / 1024 / 1024:.1f}MB) "
                  f"is larger than max chunk size. Placing in its own chunk.")
            chunks.append([package_path])
            chunk_sizes.append(package_size)
            continue

        # Try to fit in an existing chunk (first-fit)
        placed = False
        for i, chunk in enumerate(chunks):
            if chunk_sizes[i] + package_size <= max_size:
                chunk.append(package_path)
                chunk_sizes[i] += package_size
                placed = True
                break

        # Create new chunk if it doesn't fit anywhere
        if not placed:
            chunks.append([package_path])
            chunk_sizes.append(package_size)

    # Sort packages within each chunk alphabetically for consistency
    for chunk in chunks:
        chunk.sort()

    return chunks


def create_packages_tar_gz(
    output_path: Path,
    mirror_dir: Path,
    packages: List[str]
) -> None:
    """
    Create a tar.gz archive containing the specified packages.

    The archive structure mirrors the original mirror directory structure.
    """
    with tarfile.open(output_path, "w:gz") as tar:
        packages_dir = mirror_dir / "packages"
        for package in packages:
            package_path = packages_dir / package
            if package_path.exists():
                tar.add(package_path, arcname=f"mirror/packages/{package}")


def create_metadata_tar_gz(
    output_path: Path,
    mirror_dir: Path,
    metadata_files: List[str]
) -> None:
    """
    Create a tar.gz archive containing the metadata files.
    """
    with tarfile.open(output_path, "w:gz") as tar:
        for meta_file in metadata_files:
            meta_path = mirror_dir / meta_file
            if meta_path.exists():
                tar.add(meta_path, arcname=f"mirror/{meta_file}")


def main():
    # Determine mirror directory
    if len(sys.argv) > 1:
        mirror_dir = Path(sys.argv[1])
    else:
        mirror_dir = Path(__file__).parent / "mirror"

    if not mirror_dir.exists():
        print(f"Error: Mirror directory not found: {mirror_dir}")
        sys.exit(1)

    packages_dir = mirror_dir / "packages"
    if not packages_dir.exists():
        print(f"Error: Packages directory not found: {packages_dir}")
        sys.exit(1)

    # Output directory
    output_dir = Path(__file__).parent

    # Get today's date for naming
    date_str = datetime.now().strftime("%Y%m%d")

    # Metadata files
    metadata_files = ["all-packages", "registry.json"]
    metadata_size = sum(get_file_size(mirror_dir / f) for f in metadata_files if (mirror_dir / f).exists())

    print(f"Mirror directory: {mirror_dir}")
    print(f"Total mirror size: {get_dir_size(mirror_dir) / 1024 / 1024 / 1024:.2f} GB")
    print(f"Metadata files size: {metadata_size / 1024 / 1024:.2f} MB")
    print(f"Max chunk size: {MAX_CHUNK_SIZE / 1024 / 1024 / 1024:.2f} GB")
    print()

    # Get all packages with sizes
    print("Scanning packages...")
    packages = get_packages_with_sizes(packages_dir)
    print(f"Found {len(packages)} packages")

    total_packages_size = sum(size for _, size in packages)
    print(f"Total packages size: {total_packages_size / 1024 / 1024 / 1024:.2f} GB")
    print()

    # Create chunks for packages
    print("Creating chunk distribution...")
    chunks = create_chunks(packages, MAX_CHUNK_SIZE)
    print(f"Created {len(chunks)} package chunks")
    print()

    # First, create the metadata archive
    metadata_output = output_dir / f"mirror-{date_str}-metadata.tar.gz"
    print(f"Creating metadata archive: {metadata_output.name}")
    print(f"  - Files: {', '.join(metadata_files)}")
    print(f"  - Uncompressed size: {metadata_size / 1024 / 1024:.2f} MB")

    create_metadata_tar_gz(metadata_output, mirror_dir, metadata_files)

    actual_size = metadata_output.stat().st_size
    print(f"  - Compressed size: {actual_size / 1024 / 1024:.2f} MB")
    print()

    # Create package archives
    for i, chunk_packages in enumerate(chunks, 1):
        output_file = output_dir / f"mirror-{date_str}-packages-{i}.tar.gz"

        chunk_size = sum(
            get_dir_size(packages_dir / pkg)
            for pkg in chunk_packages
        )

        print(f"Creating packages chunk {i}/{len(chunks)}: {output_file.name}")
        print(f"  - Packages: {len(chunk_packages)}")
        print(f"  - Estimated uncompressed size: {chunk_size / 1024 / 1024 / 1024:.2f} GB")

        create_packages_tar_gz(output_file, mirror_dir, chunk_packages)

        actual_size = output_file.stat().st_size
        print(f"  - Compressed size: {actual_size / 1024 / 1024:.2f} MB")
        print()

    print("Done!")
    print()
    print("Created archives:")
    print(f"  {metadata_output.name}: {metadata_output.stat().st_size / 1024 / 1024:.2f} MB")
    for i in range(1, len(chunks) + 1):
        output_file = output_dir / f"mirror-{date_str}-packages-{i}.tar.gz"
        if output_file.exists():
            size_mb = output_file.stat().st_size / 1024 / 1024
            print(f"  {output_file.name}: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
