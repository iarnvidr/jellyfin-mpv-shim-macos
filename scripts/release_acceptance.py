#!/usr/bin/env python3
"""Bind a release to native and Dagger artifacts tested on the exact merged tree."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import release

REPOSITORY = "iarnvidr/jellyfin-mpv-shim-macos"
NATIVE_WORKFLOW = ".github/workflows/macos-build.yml"
CHECK_WORKFLOW = ".github/workflows/check.yml"
MAPPING_WORKFLOW = ".github/workflows/accept-native.yml"
HELPER_PATH = "scripts/release_acceptance.py"
NATIVE_ARTIFACT_PREFIX = "Jellyfin-Player-macOS-Apple-Silicon"
CHECK_ARTIFACT_PREFIX = "jellyfin-check-candidate"
MAPPING_ARTIFACT_PREFIX = "jellyfin-accepted-native"
MAX_BYTES = 1024 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def version(root):
    return (root / "VERSION").read_text().strip()


def output_names(value):
    return {
        f"Jellyfin-Player-{value}-Apple-Silicon.zip",
        f"Jellyfin-Player-macOS-{value}-Apple-Silicon.dmg",
        f"Jellyfin-Player-{value}-Source.zip",
        f"Jellyfin-Player-{value}-Build-Manifest.json",
        f"Jellyfin-Player-{value}-Native-Audit.json",
        f"Jellyfin-Player-{value}-Bundle-Inventory.json",
        f"Jellyfin-Player-{value}-Signatures.json",
        "SHA256SUMS",
    }


def event(root):
    return json.loads((root / os.environ["GITHUB_EVENT_PATH"]).read_text())


def write_native_receipt(root):
    payload = event(root)
    pr = payload.get("pull_request") or {}
    if not pr:
        raise ValueError("native candidate receipts are created only for pull requests")
    outputs = root / "outputs"
    files = {p.name: sha(p.read_bytes()) for p in outputs.iterdir() if p.is_file()
             and p.name != "native-receipt.json"}
    if set(files) != output_names(version(root)):
        raise ValueError("native output inventory is incomplete or contains unexpected files")
    receipt = {
        "schema": 1,
        "repository": os.environ["GITHUB_REPOSITORY"],
        "workflow_path": NATIVE_WORKFLOW,
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "event": os.environ["GITHUB_EVENT_NAME"],
        "workflow_sha": os.environ["GITHUB_WORKFLOW_SHA"],
        "head_sha": pr.get("head", {}).get("sha"),
        "base_sha": pr.get("base", {}).get("sha"),
        "pr_number": pr.get("number"),
        "tested_tree": git(root, "rev-parse", "HEAD^{tree}"),
        "version": version(root),
        "files": files,
    }
    (outputs / "native-receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")


def write_check_receipt(root):
    payload = event(root)
    pr = payload.get("pull_request") or {}
    if not pr:
        raise ValueError("Dagger check receipts are created only for pull requests")
    receipt = {
        "schema": 1,
        "repository": os.environ["GITHUB_REPOSITORY"],
        "workflow_path": CHECK_WORKFLOW,
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "event": os.environ["GITHUB_EVENT_NAME"],
        "workflow_sha": os.environ["GITHUB_WORKFLOW_SHA"],
        "head_sha": pr.get("head", {}).get("sha"),
        "base_sha": pr.get("base", {}).get("sha"),
        "pr_number": pr.get("number"),
        "tested_tree": git(root, "rev-parse", "HEAD^{tree}"),
        "check": "integration",
    }
    (root / "check-candidate.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")


def api(path, binary=False):
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("GH_TOKEN is required for trusted release artifact lookup")
    url = path if path.startswith("https://") else "https://api.github.com/" + path
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        safe_path = urllib.parse.urlsplit(url).path
        raise ValueError(f"GitHub API returned HTTP {exc.code} for {safe_path}") from exc
    if len(data) > MAX_BYTES:
        raise ValueError("GitHub response exceeded the bounded artifact size")
    return data if binary else json.loads(data)


def artifact_bytes(metadata):
    if metadata.get("expired") or not str(metadata.get("id", "")).isdigit():
        raise ValueError("accepted artifact is missing, expired, or has an invalid id")
    digest = metadata.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("GitHub artifact has no immutable SHA-256 digest")
    data = api(f"repos/{REPOSITORY}/actions/artifacts/{metadata['id']}/zip", binary=True)
    if "sha256:" + sha(data) != digest:
        raise ValueError("GitHub artifact digest mismatch")
    return data


def zip_members(data, expected):
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        infos = bundle.infolist()
        names = [item.filename for item in infos if not item.is_dir()]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("artifact has a missing, duplicate, or unexpected file")
        if sum(item.file_size for item in infos) > MAX_BYTES:
            raise ValueError("artifact members exceed the aggregate size limit")
        for item in infos:
            name = item.filename
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("unsafe artifact member path")
            if item.file_size > MAX_BYTES:
                raise ValueError("artifact member exceeds size limit")
        return {name: bundle.read(name) for name in names}


def trusted_blob(path, merge_sha, workflow_sha):
    encoded = urllib.parse.quote(path, safe="/")
    accepted = api(f"repos/{REPOSITORY}/contents/{encoded}?ref={merge_sha}")["sha"]
    produced = api(f"repos/{REPOSITORY}/contents/{encoded}?ref={workflow_sha}")["sha"]
    if accepted != produced:
        raise ValueError(f"producer policy file differs from accepted main: {path}")


def successful_pr_runs(workflow, pr):
    found = []
    for page in range(1, 11):
        query = urllib.parse.urlencode({"head_sha": pr["head"]["sha"], "event": "pull_request",
                                        "per_page": 100, "page": page})
        batch = api(f"repos/{REPOSITORY}/actions/workflows/{Path(workflow).name}/runs?{query}")["workflow_runs"]
        found.extend(item for item in batch
                     if item.get("repository", {}).get("full_name") == REPOSITORY
                     and item.get("head_repository", {}).get("full_name") == REPOSITORY
                     and item.get("path") == workflow
                     and item.get("head_sha") == pr["head"]["sha"]
                     and item.get("event") == "pull_request"
                      and item.get("conclusion") == "success")
        if len(batch) < 100:
            break
    if not found:
        raise ValueError(f"no successful {workflow} PR run for the exact head and base")
    return max(found, key=lambda item: (item["id"], item["run_attempt"]))


def find_artifact(run, prefix):
    artifacts = api(f"repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts?per_page=100")["artifacts"]
    name = f"{prefix}-{run['id']}-{run['run_attempt']}"
    found = [item for item in artifacts if item.get("name") == name and not item.get("expired")]
    if len(found) != 1:
        raise ValueError("exact producer run has no unique unexpired candidate artifact")
    return found[0]


def check_receipt(run, artifact, accepted_tree, pr, merge_sha, source_base_sha=None):
    if (run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or run.get("path") != CHECK_WORKFLOW or run.get("event") != "pull_request"
            or run.get("conclusion") != "success" or run.get("head_sha") != pr["head"]["sha"]):
        raise ValueError("Dagger producer is not the successful same-repository PR run")
    base_sha = pr.get("base", {}).get("sha")
    if source_base_sha and base_sha != source_base_sha:
        raise ValueError("Dagger check and native runs were tested against different bases")
    if artifact.get("name") != f"{CHECK_ARTIFACT_PREFIX}-{run['id']}-{run['run_attempt']}":
        raise ValueError("Dagger artifact name does not identify its producer attempt")
    members = zip_members(artifact_bytes(artifact), {"check-candidate.json"})
    receipt = json.loads(members["check-candidate.json"])
    expected = {
        "schema": 1, "repository": REPOSITORY, "workflow_path": CHECK_WORKFLOW,
        "run_id": run["id"], "run_attempt": run["run_attempt"], "event": "pull_request",
        "head_sha": pr["head"]["sha"], "base_sha": base_sha,
        "pr_number": pr["number"], "tested_tree": accepted_tree, "check": "integration",
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("Dagger receipt does not identify the accepted merge tree and PR")
    workflow_sha = receipt.get("workflow_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", workflow_sha):
        raise ValueError("Dagger receipt has no valid workflow revision")
    for path in (CHECK_WORKFLOW, HELPER_PATH):
        trusted_blob(path, merge_sha, workflow_sha)
    return {"run_id": run["id"], "run_attempt": run["run_attempt"],
            "artifact_id": artifact["id"], "artifact_digest": artifact["digest"],
            "artifact_name": artifact["name"], "workflow_sha": workflow_sha}


def native_receipt(root, run, artifact, data, pr, merge_sha, merge_tree):
    if (run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or run.get("path") != NATIVE_WORKFLOW or run.get("event") != "pull_request"
            or run.get("conclusion") != "success" or run.get("head_sha") != pr["head"]["sha"]
            or not pr.get("merged") or pr.get("merge_commit_sha") != merge_sha
            or pr.get("base", {}).get("ref") != "main"
            or pr.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY
            or pr.get("head", {}).get("repo", {}).get("full_name") != REPOSITORY):
        raise ValueError("native producer is not the successful same-repository PR run for this merge")
    if artifact.get("name") != f"{NATIVE_ARTIFACT_PREFIX}-{run['id']}-{run['run_attempt']}":
        raise ValueError("native artifact name does not identify its producer attempt")
    expected_names = output_names(version(root))
    members = zip_members(data, expected_names | {"native-receipt.json"})
    receipt = json.loads(members["native-receipt.json"])
    expected = {
        "schema": 1, "repository": REPOSITORY, "workflow_path": NATIVE_WORKFLOW,
        "run_id": run["id"], "run_attempt": run["run_attempt"], "event": "pull_request",
        "head_sha": pr["head"]["sha"],
        "base_sha": pr.get("base", {}).get("sha"),
        "pr_number": pr["number"], "tested_tree": merge_tree, "version": version(root),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("native receipt does not bind the accepted merge tree and PR")
    files = {name: sha(body) for name, body in members.items() if name != "native-receipt.json"}
    if receipt.get("files") != files:
        raise ValueError("native artifact files differ from the receipt inventory")
    workflow_sha = receipt.get("workflow_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", workflow_sha):
        raise ValueError("native receipt has no valid workflow revision")
    for path in (NATIVE_WORKFLOW, HELPER_PATH):
        trusted_blob(path, merge_sha, workflow_sha)
    with tempfile.TemporaryDirectory() as directory:
        for name, body in members.items():
            if name != "native-receipt.json":
                (Path(directory) / name).write_bytes(body)
        release.verify_artifacts(Path(directory), "v" + version(root))
    return receipt, files


def exact_pr_for_merge(merge_sha):
    matches = []
    for candidate in api(f"repos/{REPOSITORY}/commits/{merge_sha}/pulls"):
        if candidate.get("number"):
            pr = api(f"repos/{REPOSITORY}/pulls/{candidate['number']}")
            if pr.get("merged") and pr.get("merge_commit_sha") == merge_sha and pr.get("base", {}).get("ref") == "main":
                matches.append(pr)
    if len(matches) != 1:
        raise ValueError("main commit does not identify exactly one merged PR")
    pr = matches[0]
    if (pr.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY
            or pr.get("head", {}).get("repo", {}).get("full_name") != REPOSITORY):
        raise ValueError("fork-produced artifacts are not eligible for release promotion")
    return pr


def promote(root, merge_sha):
    if git(root, "rev-parse", "HEAD^{commit}") != merge_sha:
        raise ValueError("promotion checkout does not match the actual main merge commit")
    merge_tree = git(root, "rev-parse", "HEAD^{tree}")
    pr = exact_pr_for_merge(merge_sha)
    native_run = successful_pr_runs(NATIVE_WORKFLOW, pr)
    check_run = successful_pr_runs(CHECK_WORKFLOW, pr)
    native_artifact = find_artifact(native_run, NATIVE_ARTIFACT_PREFIX)
    check_artifact = find_artifact(check_run, CHECK_ARTIFACT_PREFIX)
    native_data = artifact_bytes(native_artifact)
    receipt, files = native_receipt(root, native_run, native_artifact, native_data, pr, merge_sha, merge_tree)
    check = check_receipt(check_run, check_artifact, merge_tree, pr, merge_sha, receipt["base_sha"])
    accepted = {
        "schema": 1, "repository": REPOSITORY, "accepted_commit": merge_sha,
        "accepted_tree": merge_tree, "pr_number": pr["number"],
        "pr_head_sha": pr["head"]["sha"], "source_base_sha": receipt["base_sha"],
        "version": version(root), "native_workflow_sha": receipt["workflow_sha"],
        "native_run_id": native_run["id"], "native_run_attempt": native_run["run_attempt"],
        "native_artifact_id": native_artifact["id"], "native_artifact_digest": native_artifact["digest"],
        "native_artifact_name": native_artifact["name"], "native_files": files,
        "check_workflow_sha": check["workflow_sha"], "check_run_id": check["run_id"],
        "check_run_attempt": check["run_attempt"], "check_artifact_id": check["artifact_id"],
        "check_artifact_digest": check["artifact_digest"], "check_artifact_name": check["artifact_name"],
    }
    (root / "accepted-native.json").write_text(json.dumps(accepted, sort_keys=True) + "\n")
    return accepted


def mapping(root, mapping_run_id, expected_commit):
    if not str(mapping_run_id).isdigit():
        raise ValueError("mapping run id must be numeric")
    run = api(f"repos/{REPOSITORY}/actions/runs/{mapping_run_id}")
    if (run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("path") != MAPPING_WORKFLOW or run.get("event") != "push"
            or run.get("head_branch") != "main" or run.get("head_sha") != expected_commit
            or run.get("conclusion") != "success"):
        raise ValueError("mapping run is not the successful trusted main promotion for this commit")
    artifacts = api(f"repos/{REPOSITORY}/actions/runs/{mapping_run_id}/artifacts?per_page=100")["artifacts"]
    name = f"{MAPPING_ARTIFACT_PREFIX}-{expected_commit}-{run['id']}-{run['run_attempt']}"
    found = [item for item in artifacts if item.get("name") == name and not item.get("expired")]
    if len(found) != 1:
        raise ValueError("accepted mapping artifact is missing, expired, or ambiguous")
    members = zip_members(artifact_bytes(found[0]), {"accepted-native.json"})
    accepted = json.loads(members["accepted-native.json"])
    if (accepted.get("repository") != REPOSITORY or accepted.get("accepted_commit") != expected_commit
            or accepted.get("accepted_tree") != git(root, "rev-parse", "HEAD^{tree}")
            or accepted.get("version") != version(root)):
        raise ValueError("accepted mapping does not match this release tree and version")
    return accepted


def verify_check_mapping(accepted, merge_sha, pr):
    run_id, attempt = accepted["check_run_id"], accepted["check_run_attempt"]
    run = api(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    if (run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or run.get("path") != CHECK_WORKFLOW or run.get("event") != "pull_request"
            or run.get("conclusion") != "success" or run.get("run_attempt") != attempt
            or run.get("head_sha") != accepted["pr_head_sha"]):
        raise ValueError("accepted Dagger check run changed identity")
    if (pr.get("number") != accepted["pr_number"] or not pr.get("merged")
            or pr.get("merge_commit_sha") != merge_sha
            or pr.get("head", {}).get("sha") != accepted["pr_head_sha"]
            or pr.get("base", {}).get("sha") != accepted["source_base_sha"]
            or pr.get("base", {}).get("ref") != "main"
            or pr.get("head", {}).get("repo", {}).get("full_name") != REPOSITORY
            or pr.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY):
        raise ValueError("accepted Dagger check run is not bound to the exact merged same-repository PR")
    artifact = find_artifact(run, CHECK_ARTIFACT_PREFIX)
    if (artifact.get("id") != accepted["check_artifact_id"]
            or artifact.get("digest") != accepted["check_artifact_digest"]
            or artifact.get("name") != accepted["check_artifact_name"]):
        raise ValueError("accepted Dagger check artifact changed identity")
    members = zip_members(artifact_bytes(artifact), {"check-candidate.json"})
    record = json.loads(members["check-candidate.json"])
    expected = {
        "schema": 1, "repository": REPOSITORY, "workflow_path": CHECK_WORKFLOW,
        "run_id": run_id, "run_attempt": attempt, "event": "pull_request",
        "head_sha": accepted["pr_head_sha"], "base_sha": accepted["source_base_sha"],
        "pr_number": accepted["pr_number"], "tested_tree": accepted["accepted_tree"],
        "check": "integration", "workflow_sha": accepted["check_workflow_sha"],
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError("accepted Dagger receipt contents changed")
    for path in (CHECK_WORKFLOW, HELPER_PATH):
        trusted_blob(path, merge_sha, record["workflow_sha"])


def retrieve(root, mapping_run_id, expected_commit, target):
    accepted = mapping(root, mapping_run_id, expected_commit)
    pr = api(f"repos/{REPOSITORY}/pulls/{accepted['pr_number']}")
    if (not pr.get("merged") or pr.get("merge_commit_sha") != expected_commit
            or pr.get("head", {}).get("sha") != accepted["pr_head_sha"]
            or pr.get("head", {}).get("repo", {}).get("full_name") != REPOSITORY):
        raise ValueError("accepted source PR no longer matches the exact main merge")
    verify_check_mapping(accepted, expected_commit, pr)
    run = api(f"repos/{REPOSITORY}/actions/runs/{accepted['native_run_id']}")
    artifacts = api(f"repos/{REPOSITORY}/actions/runs/{accepted['native_run_id']}/artifacts?per_page=100")["artifacts"]
    found = [item for item in artifacts if item.get("id") == accepted["native_artifact_id"]
             and item.get("name") == accepted["native_artifact_name"]
             and item.get("digest") == accepted["native_artifact_digest"] and not item.get("expired")]
    if len(found) != 1:
        raise ValueError("accepted native package artifact is missing, expired, or changed identity")
    data = artifact_bytes(found[0])
    receipt, files = native_receipt(root, run, found[0], data, pr, expected_commit, accepted["accepted_tree"])
    if files != accepted["native_files"] or receipt["workflow_sha"] != accepted["native_workflow_sha"]:
        raise ValueError("native artifact no longer matches its accepted mapping")
    members = zip_members(data, output_names(version(root)) | {"native-receipt.json"})
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for name in output_names(version(root)):
        (target / name).write_bytes(members[name])
    (root / "accepted-native.json").write_text(json.dumps(accepted, sort_keys=True) + "\n")
    return accepted


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    native = commands.add_parser("create-native")
    native.add_argument("--root", type=Path, default=Path.cwd())
    check = commands.add_parser("create-check")
    check.add_argument("--root", type=Path, default=Path.cwd())
    accept = commands.add_parser("promote")
    accept.add_argument("--root", type=Path, default=Path.cwd())
    accept.add_argument("--merge-sha", required=True)
    retrieve_cmd = commands.add_parser("retrieve")
    retrieve_cmd.add_argument("--root", type=Path, default=Path.cwd())
    retrieve_cmd.add_argument("--mapping-run-id", required=True)
    retrieve_cmd.add_argument("--expected-commit", required=True)
    retrieve_cmd.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create-native":
        write_native_receipt(args.root)
    elif args.command == "create-check":
        write_check_receipt(args.root)
    elif args.command == "promote":
        promote(args.root, args.merge_sha)
    else:
        retrieve(args.root, args.mapping_run_id, args.expected_commit, args.target)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"release acceptance blocked: {exc}") from exc
