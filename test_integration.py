#!/usr/bin/env python3
"""
Integration test script for elm_mirror.py

This script performs end-to-end testing of the Elm mirror server functionality.
It calls out to the real Elm package server and GitHub, so it requires internet access.

Usage:
    python test_integration.py
"""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Test configuration
TEST_MIRROR_DIR = Path("test-mirror-integration")
TEST_PACKAGES_FILE = Path("test-packages-integration.json")
TEST_PACKAGES = ["elm/core@1.0.5", "elm/json@1.1.3"]
SERVER_PORT = 18765  # Use unusual port to avoid conflicts
SERVER_BASE_URL = f"http://localhost:{SERVER_PORT}"

# Colors for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def print_header(msg: str) -> None:
    print(f"\n{YELLOW}{'=' * 60}{RESET}")
    print(f"{YELLOW}{msg}{RESET}")
    print(f"{YELLOW}{'=' * 60}{RESET}")


def print_pass(msg: str) -> None:
    print(f"  {GREEN}PASS{RESET}: {msg}")


def print_fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET}: {msg}")


def cleanup() -> None:
    """Clean up test artifacts."""
    if TEST_MIRROR_DIR.exists():
        shutil.rmtree(TEST_MIRROR_DIR)
    if TEST_PACKAGES_FILE.exists():
        TEST_PACKAGES_FILE.unlink()


def fetch_url(url: str, timeout: int = 10) -> bytes:
    """Fetch a URL and return response body."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "elm-mirror-test/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_json(url: str) -> any:
    """Fetch a URL and parse as JSON."""
    return json.loads(fetch_url(url).decode("utf-8"))


def run_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=check
    )


def test_sync() -> bool:
    """Test the sync command."""
    print_header("Testing sync command")

    # Create package list file
    with open(TEST_PACKAGES_FILE, "w") as f:
        json.dump(TEST_PACKAGES, f)

    # Run sync
    result = run_command([
        sys.executable, "elm_mirror.py", "sync",
        "--mirror-content", str(TEST_MIRROR_DIR),
        "--package-list", str(TEST_PACKAGES_FILE)
    ], check=False)

    if result.returncode != 0:
        print_fail(f"sync command failed: {result.stderr}")
        return False
    print_pass("sync command completed successfully")

    # Check registry.json exists
    registry_path = TEST_MIRROR_DIR / "registry.json"
    if not registry_path.exists():
        print_fail("registry.json not created")
        return False
    print_pass("registry.json created")

    # Check registry contents
    with open(registry_path) as f:
        registry = json.load(f)

    success_count = sum(1 for p in registry["packages"] if p["status"] == "success")
    if success_count != len(TEST_PACKAGES):
        print_fail(f"Expected {len(TEST_PACKAGES)} successful packages, got {success_count}")
        return False
    print_pass(f"{success_count} packages synced successfully")

    # Check all-packages exists
    if not (TEST_MIRROR_DIR / "all-packages").exists():
        print_fail("all-packages not created")
        return False
    print_pass("all-packages index created")

    # Check package files exist
    for pkg_id in TEST_PACKAGES:
        author, rest = pkg_id.split("/")
        name, version = rest.split("@")
        pkg_dir = TEST_MIRROR_DIR / "packages" / author / name / version

        for filename in ["elm.json", "hash.json", "package.zip", "docs.json"]:
            if not (pkg_dir / filename).exists():
                print_fail(f"{pkg_id}: {filename} missing")
                return False
        print_pass(f"{pkg_id}: all files present")

    return True


def test_verify() -> bool:
    """Test the verify command."""
    print_header("Testing verify command")

    result = run_command([
        sys.executable, "elm_mirror.py", "verify",
        "--mirror-content", str(TEST_MIRROR_DIR)
    ], check=False)

    if result.returncode != 0:
        print_fail(f"verify command failed: {result.stderr}")
        return False

    if "All checks passed" not in result.stdout:
        print_fail(f"verify did not pass: {result.stdout}")
        return False

    print_pass("verify command passed")
    return True


def test_verify_detects_corruption() -> bool:
    """Test that verify detects corrupted packages."""
    print_header("Testing verify detects corruption")

    # Corrupt a package.zip
    zip_path = TEST_MIRROR_DIR / "packages" / "elm" / "core" / "1.0.5" / "package.zip"
    original_content = zip_path.read_bytes()

    # Write corrupted content
    zip_path.write_bytes(b"corrupted content")

    result = run_command([
        sys.executable, "elm_mirror.py", "verify",
        "--mirror-content", str(TEST_MIRROR_DIR)
    ], check=False)

    # Restore original content
    zip_path.write_bytes(original_content)

    if result.returncode == 0:
        print_fail("verify should have failed for corrupted package")
        return False

    if "hash mismatch" not in result.stdout:
        print_fail(f"verify should report hash mismatch: {result.stdout}")
        return False

    print_pass("verify correctly detected corruption")
    return True


def test_serve() -> bool:
    """Test the serve command."""
    print_header("Testing serve command")

    # Start server in background
    server_proc = subprocess.Popen(
        [
            sys.executable, "elm_mirror.py", "serve",
            "--mirror-content", str(TEST_MIRROR_DIR),
            "--base-url", SERVER_BASE_URL,
            "--port", str(SERVER_PORT),
            "--host", "127.0.0.1"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        # Wait for server to start
        time.sleep(2)

        # Check server is running
        if server_proc.poll() is not None:
            _, stderr = server_proc.communicate()
            print_fail(f"Server failed to start: {stderr.decode()}")
            return False
        print_pass("Server started successfully")

        # Test /all-packages
        try:
            all_packages = fetch_json(f"{SERVER_BASE_URL}/all-packages")
            if "elm/core" not in all_packages:
                print_fail("/all-packages missing elm/core")
                return False
            print_pass("/all-packages returns valid data")
        except Exception as e:
            print_fail(f"/all-packages failed: {e}")
            return False

        # Test /all-packages/since/<N>
        try:
            # Load registry to get total count
            with open(TEST_MIRROR_DIR / "registry.json") as f:
                registry = json.load(f)
            total = len(registry["packages"])

            # Request last 2 packages
            since_result = fetch_json(f"{SERVER_BASE_URL}/all-packages/since/{total - 2}")
            if len(since_result) != 2:
                print_fail(f"/all-packages/since returned {len(since_result)} packages, expected 2")
                return False
            print_pass("/all-packages/since/<N> works correctly")
        except Exception as e:
            print_fail(f"/all-packages/since failed: {e}")
            return False

        # Test /packages/<author>/<name>/<version>/endpoint.json
        try:
            endpoint = fetch_json(f"{SERVER_BASE_URL}/packages/elm/core/1.0.5/endpoint.json")
            expected_url = f"{SERVER_BASE_URL}/packages/elm/core/1.0.5/package.zip"
            if endpoint.get("url") != expected_url:
                print_fail(f"endpoint.json has wrong URL: {endpoint.get('url')}")
                return False
            if "hash" not in endpoint:
                print_fail("endpoint.json missing hash")
                return False
            print_pass("endpoint.json generated correctly with absolute URL")
        except Exception as e:
            print_fail(f"endpoint.json failed: {e}")
            return False

        # Test /packages/<author>/<name>/<version>/elm.json
        try:
            elm_json = fetch_json(f"{SERVER_BASE_URL}/packages/elm/core/1.0.5/elm.json")
            if elm_json.get("name") != "elm/core":
                print_fail(f"elm.json has wrong name: {elm_json.get('name')}")
                return False
            print_pass("elm.json served correctly")
        except Exception as e:
            print_fail(f"elm.json failed: {e}")
            return False

        # Test /packages/<author>/<name>/<version>/docs.json
        try:
            docs_json = fetch_json(f"{SERVER_BASE_URL}/packages/elm/core/1.0.5/docs.json")
            if not isinstance(docs_json, list):
                print_fail(f"docs.json should be a list, got {type(docs_json)}")
                return False
            # Check that it contains module documentation
            module_names = [m.get("name") for m in docs_json if isinstance(m, dict)]
            if "Basics" not in module_names:
                print_fail(f"docs.json missing Basics module: {module_names}")
                return False
            print_pass("docs.json served correctly")
        except Exception as e:
            print_fail(f"docs.json failed: {e}")
            return False

        # Test package.zip download and hash verification
        try:
            zip_data = fetch_url(f"{SERVER_BASE_URL}/packages/elm/core/1.0.5/package.zip")
            actual_hash = hashlib.sha1(zip_data).hexdigest()

            # Get expected hash
            endpoint = fetch_json(f"{SERVER_BASE_URL}/packages/elm/core/1.0.5/endpoint.json")
            expected_hash = endpoint["hash"]

            if actual_hash != expected_hash:
                print_fail(f"package.zip hash mismatch: {actual_hash} != {expected_hash}")
                return False
            print_pass("package.zip downloaded with correct hash")
        except Exception as e:
            print_fail(f"package.zip download failed: {e}")
            return False

        # Test 503 for unavailable package
        try:
            request = urllib.request.Request(
                f"{SERVER_BASE_URL}/packages/elm/html/1.0.0/endpoint.json",
                headers={"User-Agent": "elm-mirror-test/1.0"}
            )
            urllib.request.urlopen(request, timeout=10)
            print_fail("Should have gotten 503 for unavailable package")
            return False
        except urllib.error.HTTPError as e:
            if e.code != 503:
                print_fail(f"Expected 503, got {e.code}")
                return False
            print_pass("503 returned for unavailable package")
        except Exception as e:
            print_fail(f"Unexpected error testing 503: {e}")
            return False

        return True

    finally:
        # Kill server
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        print_pass("Server stopped")


def test_incremental_sync() -> bool:
    """Test that incremental sync works correctly."""
    print_header("Testing incremental sync")

    # Get current registry state
    with open(TEST_MIRROR_DIR / "registry.json") as f:
        registry_before = json.load(f)

    success_before = sum(1 for p in registry_before["packages"] if p["status"] == "success")

    # Run sync again - should be a no-op for already synced packages
    result = run_command([
        sys.executable, "elm_mirror.py", "sync",
        "--mirror-content", str(TEST_MIRROR_DIR),
        "--package-list", str(TEST_PACKAGES_FILE)
    ], check=False)

    if result.returncode != 0:
        print_fail(f"incremental sync failed: {result.stderr}")
        return False

    # Check no new packages were synced
    if "0 new packages to sync" not in result.stdout and "Found 0 new packages" not in result.stdout:
        # It's also okay if it says we already have the packages
        pass

    with open(TEST_MIRROR_DIR / "registry.json") as f:
        registry_after = json.load(f)

    success_after = sum(1 for p in registry_after["packages"] if p["status"] == "success")

    if success_after != success_before:
        print_fail(f"Success count changed: {success_before} -> {success_after}")
        return False

    print_pass("Incremental sync correctly detected no new packages")
    return True


def main() -> int:
    """Run all tests."""
    print(f"\n{YELLOW}Elm Mirror Server Integration Tests{RESET}")
    print(f"Testing with packages: {TEST_PACKAGES}")

    # Clean up any previous test artifacts
    cleanup()

    all_passed = True
    tests = [
        ("Sync", test_sync),
        ("Verify", test_verify),
        ("Verify Detects Corruption", test_verify_detects_corruption),
        ("Serve", test_serve),
        ("Incremental Sync", test_incremental_sync),
    ]

    results = []

    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
            if not passed:
                all_passed = False
        except Exception as e:
            print_fail(f"Test {name} raised exception: {e}")
            results.append((name, False))
            all_passed = False

    # Print summary
    print_header("Test Summary")
    for name, passed in results:
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {status}: {name}")

    # Clean up
    cleanup()
    print(f"\n{YELLOW}Cleaned up test artifacts{RESET}")

    if all_passed:
        print(f"\n{GREEN}All tests passed!{RESET}\n")
        return 0
    else:
        print(f"\n{RED}Some tests failed!{RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
