#!/usr/bin/env python3
"""用 gh api CLI 推两个 34MB 大文件（blob+tree+commit+ref）。
用法：python scripts/push_big.py
"""
import base64, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "jiankujidu/haowallpaper-clone"
BRANCH = "master"


def gh_api(path, method="GET", body=None, timeout=600):
    cmd = ["gh", "api", "-X", method, f"repos/{REPO}/{path}"]
    if body is not None:
        with open("/tmp/_body.json", "w") as f:
            json.dump(body, f)
        cmd += ["--input", "/tmp/_body.json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    try:
        out = json.loads(r.stdout or "{}")
    except Exception:
        out = {"raw": r.stdout[:300], "err": r.stderr[:300]}
    return r.returncode, out


def main():
    files = ["downloads/data/wallpapers.json", "website/api/wallpapers.json"]
    rc_all = True
    for rel in files:
        data = (ROOT / rel).read_bytes()
        b64 = base64.b64encode(data).decode()
        print(f"\n=== {rel} ({len(data)/1024/1024:.1f} MB) ===", flush=True)

        # 1) blob
        rc, out = gh_api("git/blobs", "POST", {"content": b64, "encoding": "base64"})
        if rc != 0:
            print(f"  [BLOB ERR] rc={rc} {out}", flush=True)
            rc_all = False
            continue
        blob_sha = out["sha"]
        print(f"  blob ok {blob_sha[:12]}", flush=True)

        # 2) current ref
        rc, ref = gh_api(f"git/refs/heads/{BRANCH}")
        if rc != 0:
            print(f"  [REF ERR] {ref}", flush=True)
            rc_all = False
            continue
        base_commit = ref["object"]["sha"]

        # 3) tree
        rc, tree = gh_api("git/trees/", "POST",
                          {"tree": [{"path": rel, "mode": "100644",
                                     "type": "blob", "sha": blob_sha}]})
        if rc != 0:
            print(f"  [TREE ERR] rc={rc} {tree}", flush=True)
            rc_all = False
            continue
        new_tree = tree["sha"]

        # 4) commit
        rc, commit = gh_api("git/commits/", "POST",
                            {"message": f"push: {rel}", "tree": new_tree,
                             "parent": [base_commit]})
        if rc != 0:
            print(f"  [COMMIT ERR] rc={rc} {commit}", flush=True)
            rc_all = False
            continue
        new_commit = commit["sha"]

        # 5) update ref
        rc, out = gh_api(f"git/refs/heads/{BRANCH}", "PATCH",
                         {"sha": new_commit, "force": True})
        if rc != 0:
            print(f"  [REF-UPDATE ERR] rc={rc} {out}", flush=True)
            rc_all = False
            continue
        print(f"  OK commit {new_commit[:12]}", flush=True)

    print("\n=== done ===" if rc_all else "\n=== has errors ===", flush=True)
    sys.exit(0 if rc_all else 1)


if __name__ == "__main__":
    main()
