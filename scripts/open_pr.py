#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""open_pr.py —— 没有 gh CLI 也能开 PR：用 git 已授权的凭据调 GitHub API

用法：
    python open_pr.py --repo yandy-gif/capital-forecast --head feat/x --base main \
        --title "标题" --body-file pr.md [--proxy http://127.0.0.1:7897] [--draft]
    python open_pr.py ... --dry-run        # 只打印将要发送的内容，不调 API

令牌只从 `git credential fill` 现取现用：不打印、不写文件、不进日志。
"""
import argparse
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def credential():
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        p = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=60, env=env)
    except Exception as ex:  # noqa: BLE001
        return "", str(ex)
    if p.returncode != 0:
        return "", (p.stderr or "git credential fill 失败").strip()[:200]
    cred = dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l)
    return cred.get("password", ""), cred.get("username", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--head", required=True, help="已经 push 的分支名")
    ap.add_argument("--base", default="main")
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", default="")
    ap.add_argument("--body", default="")
    ap.add_argument("--proxy", default="")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    body = a.body
    if a.body_file:
        body = open(a.body_file, encoding="utf-8").read()
    payload = {"title": a.title, "head": a.head, "base": a.base, "body": body, "draft": bool(a.draft)}

    if a.dry_run:
        print("POST https://api.github.com/repos/%s/pulls" % a.repo)
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
        return 0

    token, user = credential()
    if not token:
        print("没有可用的 GitHub 凭据（%s）。先让用户完成一次登录。" % (user or "credential fill 空"))
        return 1
    print("凭据：%s（令牌 %d 位，不显示）" % (user or "已授权", len(token)))

    import urllib.error
    import urllib.request
    handlers = [urllib.request.ProxyHandler({"https": a.proxy, "http": a.proxy})] if a.proxy \
        else [urllib.request.ProxyHandler({})]
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/pulls" % a.repo,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "open-pr-skill"},
        method="POST")
    try:
        r = json.load(opener.open(req, timeout=90))
        print("PR #%s 已创建：%s" % (r.get("number"), r.get("html_url")))
        return 0
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        hint = {401: "令牌无效或过期", 404: "仓库/分支不存在，或令牌无权访问",
                422: "分支没有新提交、head 与 base 相同，或同名 PR 已存在"}.get(e.code, "")
        print("HTTP %s %s\n%s" % (e.code, hint, msg[:600]))
        # 已存在同名 PR 时把已有链接捞出来
        if e.code == 422 and "A pull request already exists" in msg:
            try:
                q = urllib.request.Request(
                    "https://api.github.com/repos/%s/pulls?head=%s:%s&state=open" % (
                        a.repo, a.repo.split("/")[0], a.head),
                    headers={"Authorization": "Bearer " + token, "User-Agent": "open-pr-skill"})
                for pr in json.load(opener.open(q, timeout=60)):
                    print("已存在：", pr.get("html_url"))
            except Exception:  # noqa: BLE001
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())