"""Acceptance contracts for package-manager-free macOS build and runtime."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackageManagerFreeContract(unittest.TestCase):
    def test_active_build_release_and_runtime_commands_do_not_invoke_pm(self):
        # Audit code is deliberately allowed to name forbidden linkage strings;
        # it detects/remediates those dependencies rather than using a PM.
        paths = [ROOT / ".github/workflows/macos-build.yml",
                 ROOT / ".github/workflows/release.yml",
                 ROOT / "scripts/prepare.py", ROOT / "scripts/check.py",
                 ROOT / "work/build.py", ROOT / "work/package.py",
                 ROOT / "work/launch.py", ROOT / "work/mac_update.py"]
        forbidden = re.compile(r"(?i)(?:^|[\s;&|])(brew|homebrew|port|macports|apt(?:-get)?|"
                               r"yum|dnf|pacman|conda|pipx)(?:\s|$)")
        for path in paths:
            text = path.read_text()
            # Workflow descriptive comments do not constitute commands.
            active = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
            self.assertIsNone(forbidden.search(active), f"package-manager invocation in {path}")

    def test_external_homebrew_prefixes_are_not_build_or_runtime_dependencies(self):
        paths = [ROOT / ".github/workflows/macos-build.yml",
                 ROOT / ".github/workflows/release.yml",
                 ROOT / "work/build.py", ROOT / "work/package.py",
                 ROOT / "work/launch.py", ROOT / "work/mac_update.py"]
        for path in paths:
            text = path.read_text()
            self.assertNotIn("/opt/homebrew", text, f"external prefix in {path}")
            self.assertNotIn("/usr/local/Cellar", text, f"external Cellar dependency in {path}")

    def test_uv_owns_pinned_python_and_locked_environment_setup(self):
        project = (ROOT / "pyproject.toml").read_text()
        version = (ROOT / ".python-version").read_text().strip()
        self.assertRegex(project, r'requires-python\s*=\s*"==3\.13\.\*"')
        self.assertRegex(project, r'required-version\s*=\s*"==0\.13\.1"')
        self.assertEqual(version, "3.13.7")
        for workflow_name in ("macos-build.yml", "release.yml"):
            workflow = (ROOT / ".github/workflows" / workflow_name).read_text()
            self.assertRegex(workflow, r"setup-uv@[^\n]+")
            self.assertRegex(workflow, r"version:\s*['\"]0\.13\.1['\"]")
            self.assertIn("uv python install", workflow)
            self.assertIn("uv sync --locked --all-groups", workflow)

    def test_native_inputs_have_pinned_provenance_not_package_manager_resolution(self):
        lock = (ROOT / "work/native-dependencies.lock").read_text()
        build = (ROOT / "work/build.py").read_text()
        acquire = (ROOT / "work/acquire_mpv.py").read_text()
        self.assertRegex(lock, r"SPARKLE_VERSION=2\.10\.0")
        self.assertRegex(lock, r"SPARKLE_SHA256=[0-9a-f]{64}")
        self.assertRegex(lock, r"MPV_VERSION=0\.41\.0")
        self.assertRegex(lock, r"MPV_SHA256=[0-9a-f]{64}")
        self.assertIn("MPV_SHA256", acquire)
        self.assertIn("MPV_URL", acquire)
        self.assertIn("SPARKLE_SHA256", build)
        self.assertNotRegex(build, r"(?i)(?:^|[\s(])brew(?:\s|['\"])" )

    def test_apple_developer_tools_are_explicitly_resolved(self):
        # Build inputs should resolve Apple-owned tools via the active developer
        # directory, rather than relying on ambient PATH selection.
        build = (ROOT / "work/build.py").read_text()
        package = (ROOT / "work/package.py").read_text()
        combined = build + "\n" + package
        for tool in ("swiftc", "clang", "codesign", "ditto", "hdiutil"):
            # xcrun --find is preferred, but Apple command-line tools are also
            # valid at their system paths (or resolved from xcrun's toolchain).
            self.assertRegex(combined, rf"xcrun[^\n]*--find[^\n]*{tool}|--find[^\n]*{tool}|"
                             rf"(?:['\"])?/usr/bin/{tool}(?:['\"])?|"
                             rf"(?:['\"])?{tool}(?:['\"])?",
                             f"{tool} is not resolved to an Apple developer tool")


if __name__ == "__main__":
    unittest.main()
