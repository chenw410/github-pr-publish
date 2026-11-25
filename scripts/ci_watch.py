#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_watch.py —— 等 CI 跑完，失败就把 job 日志尾部拉下来

用法：
    python ci_watch.py --repo yandy-gif/capital-forecast --ref feat/x [--proxy ...]
    python ci_watch.py --repo owner/name --ref <sha> --interval 20 --timeout 1200

只读 GitHub API（公开仓库不需要令牌；私有仓库会自动用 git 已授权的凭据）。
日志接口会 302 到 Blob 存储：跟随重定向时**不能**带 Authorization，否则 401。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API = "https://api.github.com"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def token_if_any():
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        p = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=60, env=env)
        if p.returncode == 0:
            return dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l).get("password", "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--ref", required=True, help="分支名或 commit sha")
    ap.add_argument("--proxy", default="")
    ap.add_argument("--interval", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--log-lines", type=int, default=60)
    a = ap.parse_args()

    proxy = {"https": a.proxy, "http": a.proxy} if a.proxy else {}
    plain = urllib.request.build_opener(urllib.request.ProxyHandler(proxy))
    guarded = urllib.request.build_opener(urllib.request.ProxyHandler(proxy), NoRedirect())
    tok = token_if_any()

    def headers(auth=True):
        h = {"User-Agent": "ci-watch-skill", "Accept": "application/vnd.github+json"}
        if auth and tok:
            h["Authorization"] = "Bearer " + tok
        return h

    def get(url, auth=True):
        """返回 bytes；302 时跟随且不带 Authorization。"""
        try:
            return plain.open(urllib.request.Request(url, headers=headers(auth)), timeout=90).read()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                return plain.open(urllib.request.Request(e.headers["Location"],
                                                         headers={"User-Agent": "ci-watch-skill"}),
                                  timeout=120).read()
            raise

    deadline = time.time() + a.timeout
    runs = []
    while True:
        try:
            data = json.loads(get("%s/repos/%s/commits/%s/check-runs" % (API, a.repo, a.ref)))
        except urllib.error.HTTPError as e:
            print("查询失败 HTTP %s（私有仓库需要凭据或令牌 scope）" % e.code)
            return 1
        runs = data.get("check_runs", [])
        state = ", ".join("%s=%s" % (r["name"], r["conclusion"] or r["status"]) for r in runs) or "无 check"
        print("[%s] %s" % (time.strftime("%H:%M:%S"), state))
        if runs and all(r["status"] == "completed" for r in runs):
            break
        if time.time() > deadline:
            print("等待超时，仍有关卡未完成")
            return 2
        time.sleep(a.interval)

    bad = [r for r in runs if r["conclusion"] != "success"]
    if not bad:
        print("\n全部通过：%d 个 check" % len(runs))
        return 0

    print("\n有 %d 个未成功，拉日志尾部：" % len(bad))
    for r in bad:
        job_id = r["details_url"].rstrip("/").split("/")[-1]
        print("\n==== %s（%s）job %s ====" % (r["name"], r["conclusion"], job_id))
        try:
            txt = get("%s/repos/%s/actions/jobs/%s/logs" % (API, a.repo, job_id)).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            print("  日志拉取失败 HTTP %s" % e.code)
            continue
        lines = [l for l in txt.splitlines() if l.strip()]
        print("\n".join(lines[-a.log_lines:]))
    return 1


if __name__ == "__main__":
    sys.exit(main())