"""Fail-closed release tooling for immutable Sparkle updates and appcast publication."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
GATES = ("gui_smoke", "sparkle_update", "fresh_install", "macos15", "current_macos", "signing_review", "artifact_review", "source_review")
FEED_URL = "https://raw.githubusercontent.com/iarnvidr/jellyfin-mpv-shim-macos/updates/appcast.xml"
ASSET_ROOT = "https://github.com/iarnvidr/jellyfin-mpv-shim-macos/releases/download/"
SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"

def version():
    value = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value): raise ValueError("VERSION must be stable numeric semver")
    return value

def validate_tag(tag):
    expected = "v" + version()
    if tag != expected: raise ValueError(f"tag {tag!r} does not match VERSION ({expected})")

def require_gates(env=os.environ):
    # Require separately recorded evidence, not a single workflow toggle.
    missing = [k for k in GATES if env.get("QUALIFY_" + k.upper()) != "true" or
               not env.get("EVIDENCE_" + k.upper(), "").strip()]
    if missing: raise ValueError("production qualification incomplete: " + ", ".join(missing))

def checksum(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""): h.update(block)
    return h.hexdigest()

def validate_run(run, expected_sha, repository="iarnvidr/jellyfin-mpv-shim-macos"):
    if not isinstance(run, dict) or not str(run.get("id", "")).isdigit(): raise ValueError("invalid GitHub Actions run id")
    if run.get("repository", {}).get("full_name") != repository: raise ValueError("run repository mismatch")
    if run.get("path") != ".github/workflows/macos-build.yml": raise ValueError("run workflow mismatch")
    if run.get("conclusion") != "success": raise ValueError("run must have succeeded")
    if run.get("event") not in ("push", "workflow_dispatch"): raise ValueError("run event is not authorized")
    if run.get("head_branch") not in ("main", "shipping"): raise ValueError("run branch is not authorized")
    if run.get("head_sha") != expected_sha: raise ValueError("run commit does not match trusted commit")
    return int(run["id"])

def parse_signature(output):
    match=re.search(r'edSignature="([A-Za-z0-9+/=_-]+)"', output)
    if not match: raise ValueError("official sign_update returned no EdDSA signature")
    return {"edSignature":match.group(1),"algorithm":"EdDSA","format":"Sparkle"}

def verify_artifacts(directory, tag):
    """Verify exact package.py deliverables and all checksums, including source."""
    validate_tag(tag)
    d=Path(directory); ver=tag.removeprefix("v")
    archive=f"Jellyfin-Player-{ver}-Apple-Silicon.zip"
    dmg=f"Jellyfin-Player-macOS-{ver}-Apple-Silicon.dmg"
    source=f"Jellyfin-Player-{ver}-Source.zip"
    manifest=f"Jellyfin-Player-{ver}-Build-Manifest.json"
    required={dmg,archive,source,"SHA256SUMS",manifest}
    names={p.name for p in d.iterdir() if p.is_file()}
    if not required <= names: raise ValueError("missing release assets: "+", ".join(sorted(required-names)))
    sums={}
    for line in (d/"SHA256SUMS").read_text().splitlines():
        m=re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)",line)
        if not m or m[2] in sums: raise ValueError("malformed or duplicate SHA256SUMS entry")
        sums[m[2]]=m[1]
    expected=required-{"SHA256SUMS"}
    if set(sums)!=expected: raise ValueError("SHA256SUMS must list exactly the release assets")
    for name in expected:
        if sums.get(name)!=checksum(d/name): raise ValueError(f"checksum mismatch: {name}")
    return {"version":ver,"archive":archive,"dmg":dmg,"source":source,"manifest":manifest,"length":(d/archive).stat().st_size}

def sign_archive(archive, private_key, sign_update):
    if not private_key: raise ValueError("SPARKLE_PRIVATE_KEY secret required")
    if not Path(sign_update).is_file(): raise ValueError("pinned official sign_update executable required")
    if not Path(archive).is_file(): raise ValueError("update archive missing")
    # Sparkle's official sign_update accepts the key via stdin; never put secret in argv/logs.
    result=subprocess.run([sign_update, "--ed-key-file", "-", archive], input=private_key, text=True, capture_output=True, check=True)
    return parse_signature(result.stdout+result.stderr)

def _feed_entries(data):
    root=ET.fromstring(data)
    channel=root.find("channel")
    if channel is None: raise ValueError("appcast missing channel")
    return channel, channel.findall("item")

def update_feed(existing, metadata, tag, url=None):
    root=ET.fromstring(existing)
    channel=root.find("channel")
    if channel is None: raise ValueError("appcast missing channel")
    items=channel.findall("item")
    ver=tag.removeprefix("v")
    for item in items:
        old=item.find(f"{{{SPARKLE_NS}}}shortVersionString")
        if old is not None and old.text==ver: raise ValueError("version already exists; published versions immutable")
    if items:
        old=items[0].find(f"{{{SPARKLE_NS}}}shortVersionString")
        if old is None or tuple(map(int,ver.split("."))) <= tuple(map(int,old.text.split("."))): raise ValueError("appcast update must be strictly newer")
    if metadata.get("version") != ver or not metadata.get("signature") or not isinstance(metadata.get("length"),int) or not metadata.get("minimum_os") or not metadata.get("asset_url") or not metadata.get("feed_url") or not metadata.get("release_notes"):
        raise ValueError("incomplete or mismatched appcast metadata")
    item=ET.Element("item")
    ET.SubElement(item,f"{{{SPARKLE_NS}}}version").text=ver
    ET.SubElement(item,"title").text=ver
    ET.SubElement(item,f"{{{SPARKLE_NS}}}shortVersionString").text=ver
    ET.SubElement(item,f"{{{SPARKLE_NS}}}minimumSystemVersion").text=metadata["minimum_os"]
    ET.SubElement(item,"description").text=metadata["release_notes"]
    ET.SubElement(item,"enclosure",{"url":metadata["asset_url"],"length":str(metadata["length"]),"type":"application/octet-stream",f"{{{SPARKLE_NS}}}edSignature":metadata["signature"]})
    channel.insert(0,item)
    if metadata["feed_url"] != FEED_URL: raise ValueError("feed identity mismatch")
    return ET.tostring(root,encoding="utf-8",xml_declaration=True)


def public_asset(url, expected_length):
    if not url.startswith(ASSET_ROOT) or ".." in url: raise ValueError("asset URL must be an immutable GitHub release URL")
    req=urllib.request.Request(url,method="HEAD")
    with urllib.request.urlopen(req,timeout=30) as r:
        if r.status!=200 or int(r.headers.get("Content-Length",-1))!=expected_length: raise ValueError("public release asset unavailable or wrong length")

def main():
    p=argparse.ArgumentParser(); p.add_argument("command",choices=("validate-tag","validate-run","require-gates","checksum","verify-artifacts","sign","publish-feed")); p.add_argument("value",nargs="?"); p.add_argument("--feed"); p.add_argument("--metadata"); p.add_argument("--asset-url"); p.add_argument("--sign-update",default="sign_update")
    a=p.parse_args()
    try:
        if a.command=="validate-tag": validate_tag(a.value or "")
        elif a.command=="validate-run":
            run=json.loads(Path(a.value).read_text())
            validate_run(run, os.environ.get("TRUSTED_SHA", ""))
        elif a.command=="require-gates": require_gates()
        elif a.command=="checksum": print(checksum(a.value))
        elif a.command=="verify-artifacts":
            import json
            result=verify_artifacts(a.value,a.metadata or "")
            print(json.dumps(result,sort_keys=True))
        elif a.command=="sign": print(sign_archive(a.value,os.environ.get("SPARKLE_PRIVATE_KEY"),a.sign_update))
        else:
            require_gates(); import json
            metadata=json.loads(Path(a.metadata).read_text()); public_asset(a.asset_url,metadata["length"])
            old=Path(a.feed).read_bytes(); new=update_feed(old,metadata,a.value)
            # Write to caller-provided staging path; branch commit/push is separate atomic operation.
            candidate=Path(a.feed+".candidate")
            candidate.write_bytes(new)
            if os.environ.get("RELEASE_PUBLISH") == "true":
                if not os.environ.get("GITHUB_REF", "").startswith("refs/tags/v"):
                    raise ValueError("publication requires trusted version tag ref")
                raise ValueError("publication transport must be orchestrated by trusted release job")
    except (ValueError,OSError,KeyError,ET.ParseError,subprocess.SubprocessError) as e:
        print(f"release check failed: {e}",file=sys.stderr); return 1
    return 0
if __name__=="__main__": raise SystemExit(main())
