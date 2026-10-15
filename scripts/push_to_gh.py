#!/usr/bin/env python3
"""通过 GitHub REST API 把项目文件推上 GitHub（绕开被 502 挡住的 git 协议 443 端口）。
用法：python scripts/push_to_gh.py
策略：
  - 每个文件先 GET 拿当前 sha，再 PUT Contents API 创建/更新
  - 文件分小（≤1MB，直接 Contents API）和大（>1MB，走 blob+tree+commit+ref）两类
"""
import base64, json, os, subprocess, sys
from pathlib import Path
import urllib.request, urllib.error

ROOT = Path(__file__).resolve().parent.parent
REPO = "jiankujidu/haowallpaper-clone"
BRANCH = "master"

SKIP_DIRS = {".git", ".workbuddy", "__pycache__", "posters", "videos", "checkpoint"}
SKIP_FILES = {"scrape_full.log", "preview.log", "push_to_gh.py"}


def gh_token():
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def api(path, method="GET", body=None, token=None, timeout=300):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "User-Agent": "workbuddy-push"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def ensure_branch(token):
    st, ref = api(f"git/refs/heads/{BRANCH}", token=token)
    if st == 200:
        print(f">>> 分支 {BRANCH} 已存在")
        return
    st, empty = api("git/trees/", token=token, method="POST", body={"tree": []})
    if st != 201:
        sys.exit(f"[ERR] 建空 tree {st} {empty}")
    st, commit = api("git/commits/", token=token, method="POST",
                     body={"message": "initial", "tree": empty["sha"]})
    if st != 201:
        sys.exit(f"[ERR] 建 commit {st} {commit}")
    st, ref = api(f"git/refs/heads/{BRANCH}", token=token, method="POST",
                  body={"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    if st != 201:
        sys.exit(f"[ERR] 建 ref {st} {ref}")
    print(f">>> 已创建分支 {BRANCH}")


def push_file(token, rel, b64, size):
    """单个文件：先拿 sha，再 PUT。"""
    st, cur = api(f"contents/{rel}", token=token)
    cur_sha = cur.get("sha", "")
    body = {"message": f"push: {rel}", "branch": BRANCH,
            "path": rel, "content": b64, "encoding": "base64"}
    if cur_sha:
        body["sha"] = cur_sha
    st, out = api(f"contents/{rel}", "PUT", body, token, timeout=120)
    if st in (200, 201):
        print(f"  [ok {size/1024:6.0f}KB] {rel}", flush=True)
        return True
    print(f"  [ERR {st}] {rel}: {str(out.get('message',''))[:160]}", flush=True)
    return False


def push_big_files(token, files):
    """大文件：blob+tree+commit+ref。"""
    if not files:
        return 0
    print(f"\n>>> 推大文件（{len(files)} 个）...")

    st, ref = api(f"git/refs/heads/{BRANCH}", token=token)
    if st != 200:
        return 0
    base_commit = ref["object"]["sha"]

    tree_items = []
    for rel, b64, size in files:
        st, out = api("git/blobs", "POST", {"content": b64, "encoding": "base64"},
                      token, timeout=600)
        if st != 201:
            print(f"  [BLOB ERR {st}] {rel}: {str(out.get('message',''))[:160]}", flush=True)
            return 0
        tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": out["sha"]})
        print(f"  [blob {size/1024/1024:5.1f}MB] {rel}", flush=True)

    st, out = api("git/trees/", "POST", {"tree": tree_items}, token, timeout=300)
    if st != 201:
        print(f"[TREE ERR {st}] {str(out.get('message',''))[:160]}", flush=True)
        return 0
    new_tree = out["sha"]

    st, out = api("git/commits/", "POST",
                  {"message": "push: large files", "tree": new_tree,
                   "parent": [base_commit]}, token, timeout=120)
    if st != 201:
        print(f"[COMMIT ERR {st}] {str(out.get('message',''))[:160]}", flush=True)
        return 0
    new_commit = out["sha"]

    st, out = api(f"git/refs/heads/{BRANCH}", "PATCH",
                  {"sha": new_commit, "force": True}, token, timeout=120)
    if st != 200:
        print(f"[REF ERR {st}] {str(out.get('message',''))[:160]}", flush=True)
        return 0
    print(f"  >> 大文件已提交 {new_commit[:12]}", flush=True)
    return len(files)


def main():
    token = gh_token()
    ensure_branch(token)

    small, big = [], []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            fp = Path(dirpath) / fn
            rel = fp.relative_to(ROOT).as_posix()
            data = fp.read_bytes()
            b64 = base64.b64encode(data).decode()
            if len(data) <= 1024 * 1024:
                small.append((rel, b64, len(data)))
            else:
                big.append((rel, b64, len(data)))

    small.sort(key=lambda x: x[0])
    big.sort(key=lambda x: x[0])
    total = sum(s[2] for s in small) + sum(b[2] for b in big)
    print(f"\n>>> 共 {len(small)} 小文件 + {len(big)} 大文件，{total/1024/1024:.1f} MB")

    ok = sum(push_file(token, rel, b64, size) for rel, b64, size in small)
    okb = push_big_files(token, big)

    print(f"\n=== 结果：小文件 {ok}/{len(small)}，大文件 {okb}/{len(big)} ===")
    print(f"查看：https://github.com/{REPO}", flush=True)


if __name__ == "__main__":
    main()
