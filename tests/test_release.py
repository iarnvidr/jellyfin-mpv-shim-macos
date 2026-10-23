import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release

class ReleaseTests(unittest.TestCase):
    def test_tag_and_gates(self):
        release.validate_tag("v" + release.version())
        with self.assertRaises(ValueError): release.validate_tag("v9.9.9")
        with self.assertRaises(ValueError): release.require_gates({})
        evidence = {"QUALIFY_" + k.upper(): "true" for k in release.GATES}
        evidence.update({"EVIDENCE_" + k.upper(): "https://example.invalid/record" for k in release.GATES})
        release.require_gates(evidence)
    def test_checksum(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"artifact"); f.flush()
            self.assertEqual(release.checksum(f.name), "c7c5c1d70c5dec4416ab6158afd0b223ef40c29b1dc1f97ed9428b94d4cadb1c")
    def test_appcast_strict_monotonic_preserves_entries(self):
        xml=b'<rss version="2.0"><channel><title>Feed</title><item><sparkle:shortVersionString xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">0.1.0</sparkle:shortVersionString></item></channel></rss>'
        meta={"minimum_os":"15.0","release_notes":"notes","version":"0.2.0","asset_url":release.ASSET_ROOT+"v0.2.0/app.zip","feed_url":release.FEED_URL,"length":10,"signature":"sig"}
        out=release.update_feed(xml,meta,"v0.2.0",release.FEED_URL)
        self.assertIn(b"0.1.0",out); self.assertIn(b"0.2.0",out)
        item=release._feed_entries(out)[1][0]
        self.assertEqual(len(item.findall(f"{{{release.SPARKLE_NS}}}shortVersionString")),1)
        for tag in ("v0.2.0","v0.1.0"):
            with self.assertRaises(ValueError): release.update_feed(out,meta,tag,release.FEED_URL)
    def test_feed_rejects_wrong_url_and_invalid_xml(self):
        with self.assertRaises(Exception): release.update_feed(b'<bad',{},"v0.2.0","https://bad")
        with self.assertRaises(Exception): release.update_feed(b'<rss/>',{},"v0.2.0","https://bad")
    def test_signer_uses_official_stdin_key_syntax(self):
        import unittest.mock
        with tempfile.NamedTemporaryFile() as archive, tempfile.NamedTemporaryFile() as tool:
            tool.write(b"tool"); tool.flush()
            result = unittest.mock.Mock(stdout='sparkle:edSignature="signed"', stderr='')
            with unittest.mock.patch.object(release.subprocess, "run", return_value=result) as run:
                self.assertEqual(release.sign_archive(archive.name, "private", tool.name)["edSignature"], "signed")
                args = run.call_args
                self.assertEqual(args.args[0][1:3], ["--ed-key-file", "-"])
                self.assertEqual(args.kwargs["input"], "private")
    def test_signature_structured_and_bad_output_rejected(self):
        self.assertEqual(release.parse_signature('sparkle:edSignature="abc123=="'), {"edSignature":"abc123==","algorithm":"EdDSA","format":"Sparkle"})
        with self.assertRaises(ValueError): release.parse_signature("no signature")
    def test_run_provenance_rejects_untrusted_runs(self):
        good={"id":123,"repository":{"full_name":"iarnvidr/jellyfin-mpv-shim-macos"},"path":".github/workflows/macos-build.yml","conclusion":"success","event":"push","head_branch":"main","head_sha":"a"*40}
        self.assertEqual(release.validate_run(good,"a"*40),123)
        for key,value in (("conclusion","failure"),("path","evil.yml"),("event","pull_request"),("head_branch","fork"),("head_sha","b"*40)):
            bad=dict(good); bad[key]=value
            with self.assertRaises(ValueError): release.validate_run(bad,"a"*40)
        with self.assertRaises(ValueError): release.validate_run(dict(good,repository={"full_name":"attacker/repo"}),"a"*40)
    def test_artifact_id_uses_api_identity(self):
        self.assertEqual(release.find_run_artifact({"artifacts":[{"id":987,"name":"wanted","expired":False}]},"wanted"),987)
        for artifacts in ({"artifacts":[{"id":1,"name":"other","expired":False}]},{"artifacts":[{"id":1,"name":"wanted","expired":True}]},{"artifacts":[{"id":1,"name":"wanted","expired":False},{"id":2,"name":"wanted","expired":False}]}):
            with self.assertRaises(ValueError): release.find_run_artifact(artifacts,"wanted")
    def test_signature_asset_added_to_checksum_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); (d/"SHA256SUMS").write_text("a"*64+"  package.zip\\n")
            sig=release.write_signature_assets(d,{"edSignature":"abc","algorithm":"EdDSA","format":"Sparkle"},"package.zip")
            data=json.loads(sig.read_text())
            self.assertEqual(data["edSignature"],"abc")
            row=(d/"SHA256SUMS").read_text().splitlines()[-1]
            self.assertEqual(row,f"{release.checksum(sig)}  signature.json")
    def test_signer_secret_is_not_argument(self):
        with tempfile.NamedTemporaryFile() as archive:
            with self.assertRaises((FileNotFoundError, ValueError)): release.sign_archive(archive.name,None,"nonexistent-sign_update")

if __name__ == "__main__": unittest.main()
