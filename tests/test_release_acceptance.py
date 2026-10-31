import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release
import release_acceptance as acceptance


class ReleaseAcceptanceTests(unittest.TestCase):
    def app_outputs(self, root):
        value = release.version()
        outputs = root / "outputs"
        outputs.mkdir()
        for name in acceptance.output_names(value):
            (outputs / name).write_bytes(b"fixture output: " + name.encode())
        targets = [
            {"path": ".", "valid": True},
            {"path": "Contents/Resources/mpv.app", "valid": True},
            {"path": "Contents/Resources/mpv.app/Contents/MacOS/mpv", "valid": True},
            {"path": "Contents/Resources/mpv.app/Contents/Frameworks/libMoltenVK.dylib", "valid": True},
        ]
        signature = outputs / f"Jellyfin-Player-{value}-Signatures.json"
        signature.write_text(json.dumps({"valid": True, "targets": targets}))
        (outputs / "SHA256SUMS").write_text("".join(
            f"{release.checksum(path)}  {path.name}\n"
            for path in sorted(outputs.iterdir()) if path.name != "SHA256SUMS"
        ))
        return outputs

    def test_native_receipt_creation_binds_run_tree_and_exact_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERSION").write_text(release.version())
            outputs = self.app_outputs(root)
            payload = {"pull_request": {
                "number": 44,
                "head": {"sha": "b" * 40},
                "base": {"sha": "f" * 40},
            }}
            event_path = root / "event.json"
            event_path.write_text(json.dumps(payload))
            env = {
                "GITHUB_EVENT_PATH": str(event_path), "GITHUB_REPOSITORY": acceptance.REPOSITORY,
                "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
                "GITHUB_EVENT_NAME": "pull_request", "GITHUB_WORKFLOW_SHA": "a" * 40,
            }
            with patch.dict(os.environ, env, clear=False), patch.object(acceptance, "git", return_value="c" * 40):
                acceptance.write_native_receipt(root)
            record = json.loads((outputs / "native-receipt.json").read_text())
            self.assertEqual(record["tested_tree"], "c" * 40)
            self.assertEqual(record["base_sha"], "f" * 40)
            self.assertEqual(set(record["files"]), acceptance.output_names(release.version()))

    def test_native_candidate_rejects_wrong_tree_and_fork_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERSION").write_text(release.version())
            outputs = self.app_outputs(root)
            files = {p.name: p.read_bytes() for p in outputs.iterdir() if p.name != "SHA256SUMS"}
            files["SHA256SUMS"] = (outputs / "SHA256SUMS").read_bytes()
            receipt = {
                "schema": 1, "repository": acceptance.REPOSITORY,
                "workflow_path": acceptance.NATIVE_WORKFLOW, "run_id": 123,
                "run_attempt": 2, "event": "pull_request", "workflow_sha": "a" * 40,
                "head_sha": "b" * 40, "base_sha": "f" * 40, "pr_number": 44,
                "tested_tree": "c" * 40, "version": release.version(),
                "files": {name: acceptance.sha(body) for name, body in files.items()},
            }
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for name, body in files.items():
                    bundle.writestr(name, body)
                bundle.writestr("native-receipt.json", json.dumps(receipt))
            run = {
                "id": 123, "run_attempt": 2, "repository": {"full_name": acceptance.REPOSITORY},
                "head_repository": {"full_name": acceptance.REPOSITORY},
                "path": acceptance.NATIVE_WORKFLOW, "conclusion": "success",
                "event": "pull_request", "head_sha": "b" * 40,
                "pull_requests": [{"number": 44, "base": {"sha": "f" * 40}}],
            }
            pr = {
                "number": 44, "merged": True, "merge_commit_sha": "d" * 40,
                "head": {"sha": "b" * 40, "repo": {"full_name": acceptance.REPOSITORY}},
                "base": {"sha": "f" * 40, "ref": "main", "repo": {"full_name": acceptance.REPOSITORY}},
            }
            artifact = {"name": f"{acceptance.NATIVE_ARTIFACT_PREFIX}-123-2"}
            with patch.object(acceptance, "trusted_blob"):
                with self.assertRaisesRegex(ValueError, "accepted merge tree"):
                    acceptance.native_receipt(root, run, artifact, archive.getvalue(), pr, "d" * 40, "e" * 40)
                pr["head"]["repo"]["full_name"] = "fork/jellyfin"
                with self.assertRaisesRegex(ValueError, "same-repository PR"):
                    acceptance.native_receipt(root, run, artifact, archive.getvalue(), pr, "d" * 40, "c" * 40)

    def test_dagger_receipt_requires_exact_successful_run_and_digest(self):
        receipt = {
            "schema": 1, "repository": acceptance.REPOSITORY,
            "workflow_path": acceptance.CHECK_WORKFLOW, "run_id": 777,
            "run_attempt": 1, "event": "pull_request", "workflow_sha": "a" * 40,
            "head_sha": "b" * 40, "base_sha": "f" * 40, "pr_number": 44,
            "tested_tree": "c" * 40, "check": "integration",
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("check-candidate.json", json.dumps(receipt))
        data = archive.getvalue()
        artifact = {
            "id": 999, "name": "jellyfin-check-candidate-777-1",
            "digest": "sha256:" + acceptance.sha(data), "expired": False,
        }
        run = {
            "id": 777, "run_attempt": 1, "repository": {"full_name": acceptance.REPOSITORY},
            "head_repository": {"full_name": acceptance.REPOSITORY},
            "path": acceptance.CHECK_WORKFLOW, "conclusion": "success",
            "event": "pull_request", "head_sha": "b" * 40,
            "pull_requests": [{"number": 44, "base": {"sha": "f" * 40}}],
        }
        pr = {
            "number": 44, "head": {"sha": "b" * 40},
            "base": {"sha": "f" * 40},
        }
        def api_fn(path, binary=False):
            if path.endswith("/actions/artifacts/999/zip"):
                return data
            raise AssertionError(path)
        with patch.object(acceptance, "api", side_effect=api_fn), patch.object(acceptance, "trusted_blob"):
            result = acceptance.check_receipt(run, artifact, "c" * 40, pr, "d" * 40)
        self.assertEqual(result["artifact_id"], 999)
        with patch.object(acceptance, "api", side_effect=api_fn), patch.object(acceptance, "trusted_blob"):
            with self.assertRaisesRegex(ValueError, "different bases"):
                acceptance.check_receipt(run, artifact, "c" * 40, pr, "d" * 40, "e" * 40)
        artifact["expired"] = True
        with patch.object(acceptance, "api", side_effect=api_fn), patch.object(acceptance, "trusted_blob"):
            with self.assertRaisesRegex(ValueError, "expired"):
                acceptance.check_receipt(run, artifact, "c" * 40, pr, "d" * 40)

    def test_artifact_zip_rejects_traversal_and_duplicates(self):
        traversal = io.BytesIO()
        with zipfile.ZipFile(traversal, "w") as bundle:
            bundle.writestr("../escape", b"bad")
        with self.assertRaisesRegex(ValueError, "missing, duplicate, or unexpected"):
            acceptance.zip_members(traversal.getvalue(), {"expected"})
        duplicate = io.BytesIO()
        with zipfile.ZipFile(duplicate, "w") as bundle:
            bundle.writestr("expected", b"one")
            bundle.writestr("expected", b"two")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            acceptance.zip_members(duplicate.getvalue(), {"expected"})

    def test_mapping_is_main_only_and_release_uses_mapping_run(self):
        root = ROOT
        map_workflow = (root / ".github/workflows/accept-native.yml").read_text()
        release_workflow = (root / ".github/workflows/release.yml").read_text()
        native_workflow = (root / ".github/workflows/macos-build.yml").read_text()
        self.assertIn("push:\n    branches: [main]", map_workflow)
        self.assertIn("--merge-sha \"$GITHUB_SHA\"", map_workflow)
        self.assertIn("${{ github.run_id }}-${{ github.run_attempt }}", map_workflow)
        self.assertIn("mapping_run_id:", release_workflow)
        self.assertIn("--mapping-run-id \"$MAPPING_RUN_ID\"", release_workflow)
        self.assertNotIn("validate-run", release_workflow)
        self.assertIn("branches: [main]", native_workflow)

    def test_mapping_requires_successful_main_run_and_attempt_specific_artifact(self):
        accepted = {
            "schema": 1, "repository": acceptance.REPOSITORY,
            "accepted_commit": "a" * 40, "accepted_tree": "b" * 40,
            "version": release.version(),
        }
        run = {
            "id": 77, "run_attempt": 2,
            "repository": {"full_name": acceptance.REPOSITORY},
            "path": acceptance.MAPPING_WORKFLOW, "event": "push",
            "head_branch": "main", "head_sha": "a" * 40, "conclusion": "success",
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("accepted-native.json", json.dumps(accepted))
        artifacts = [{
            "id": 99,
            "name": f"{acceptance.MAPPING_ARTIFACT_PREFIX}-{'a' * 40}-77-2",
            "digest": "sha256:" + "c" * 64,
            "expired": False,
        }]
        with patch.object(acceptance, "api", side_effect=[run, {"artifacts": artifacts}]), \
                patch.object(acceptance, "artifact_bytes", return_value=archive.getvalue()), \
                patch.object(acceptance, "git", return_value="b" * 40):
            result = acceptance.mapping(ROOT, "77", "a" * 40)
        self.assertEqual(result, accepted)
        artifacts[0]["name"] = f"{acceptance.MAPPING_ARTIFACT_PREFIX}-{'a' * 40}-77-1"
        with patch.object(acceptance, "api", side_effect=[run, {"artifacts": artifacts}]), \
                patch.object(acceptance, "artifact_bytes", return_value=archive.getvalue()), \
                patch.object(acceptance, "git", return_value="b" * 40):
            with self.assertRaisesRegex(ValueError, "missing, expired, or ambiguous"):
                acceptance.mapping(ROOT, "77", "a" * 40)


if __name__ == "__main__":
    unittest.main()
