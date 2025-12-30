#!/usr/bin/env bash
#
# Script to download and reconstitute the mirror directory from GitHub releases.
#
# Usage: ./download_preseeded_mirror.sh [output_directory]
#
# If output_directory is not specified, extracts to current directory.
#

set -e

# GitHub release base URL
RELEASE_URL="https://github.com/changlinli/elm-mirror-server/releases/download/v0.1"

# Archive files to download (update this array when new archives are uploaded)
ARCHIVES=(
    "mirror-20251224-metadata.tar.gz"
    "mirror-20251224-packages-1.tar.gz"
    "mirror-20251224-packages-2.tar.gz"
)

# Output directory (default: current directory)
OUTPUT_DIR="${1:-.}"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Temporary directory for downloads
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo "Downloading mirror archives from GitHub releases..."
echo "Release URL: $RELEASE_URL"
echo "Output directory: $OUTPUT_DIR"
echo

# Download all archives
for archive in "${ARCHIVES[@]}"; do
    url="$RELEASE_URL/$archive"
    dest="$TEMP_DIR/$archive"

    echo "Downloading $archive..."
    curl -L -o "$dest" "$url"

    if [ ! -f "$dest" ]; then
        echo "Error: Failed to download $archive"
        exit 1
    fi

    echo "  Downloaded: $(du -h "$dest" | cut -f1)"
done

echo
echo "Extracting archives..."

# Extract all archives to output directory
for archive in "${ARCHIVES[@]}"; do
    echo "Extracting $archive..."
    tar -xzf "$TEMP_DIR/$archive" -C "$OUTPUT_DIR"
done

echo
echo "Done! Mirror directory reconstituted at: $OUTPUT_DIR/mirror"
echo
echo "Contents:"
ls -la "$OUTPUT_DIR/mirror/"
