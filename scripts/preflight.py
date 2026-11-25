#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight.py —— 上传 GitHub 前的环境与敏感数据体检

用法：
    python preflight.py --repo-dir .                 # 自动探测代理
    python preflight.py --repo-dir . --proxy http://127.0.0.1:7897
    python preflight.py --repo-dir . --json

退出码 0 = 可以继续；1 = 有阻塞项（敏感文件 / 无 git / 目标不可达且无代理）
只依赖标准库；从不打印令牌本身。
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys

PROXY_CANDIDATES = [7890, 7897, 1080, 10809, 8080, 3128, 8888, 6152]
BLOCK_EXT = {".db", ".sqlite", ".sqlite3", ".xlsx", ".xls", ".xlsm", ".csv", ".tsv",
             ".zip", ".png", ".jpg", ".jpeg", ".pdf", ".log", ".pid", ".pyc"}
BLOCK_DIRS = {"uploads", "backup", "修复备份", "测试样例", "tmp", ".runtime", "node_modules",
              ".venv", "venv", "__pycache__", ".workbuddy", ".archify", ".codex", ".idea"}
SECRET_RE = re.compile(r"(?i)(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}"
                       r"|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|AKIA[0-9A-Z]{16})")
ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+")
LONGNUM_RE = re.compile(r"\d{12,}")
BIG_BYTES = 2 * 1024 * 1024

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run(cmd, cwd=None, timeout=60, env=None):
    e = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=e)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as ex:
        return -1, "", str(ex)


def reachable(host, port, timeout=4.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def git_version():
    rc, out, _ = run(["git", "--version"], timeout=15)
    return out.strip() if rc == 0 else None


def git_probe(proxy, timeout=40):
    """用 git 自己发一次请求：socket 通不代表 git 通（git 的 DNS 可能与系统不同）。"""
    cmd = ["git"]
    if proxy:
        cmd += ["-c", "http.proxy=" + proxy]
    cmd += ["ls-remote", "--heads", "https://github.com/git/git", "master"]
    rc, out, err = run(cmd, timeout=timeout)
    return rc == 0, (err or out).strip().splitlines()[:2]


def repo_state(d):
    rc, _, _ = run(["git", "rev-parse", "--git-dir"], cwd=d, timeout=15)
    if rc != 0:
        return None
    st = {}
    for key, cmd in (("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
                     ("remote", ["git", "remote", "-v"]),
                     ("dirty", ["git", "status", "--porcelain"]),
                     ("author", ["git", "log", "-1", "--pretty=%an | %ae"])):
        rc, out, err = run(cmd, cwd=d, timeout=20)
        st[key] = out.strip() if rc == 0 else (err.strip() or "")
    return st


def credential_ok():
    """只报告是否已有可用凭据与长度，不返回令牌内容。"""
    inp = "protocol=https\nhost=github.com\n\n"
    try:
        p = subprocess.run(["git", "credential", "fill"], input=inp, capture_output=True,
                           text=True, timeout=30,
                           env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never"))
    except Exception as ex:  # noqa: BLE001
        return False, 0, str(ex)
    if p.returncode != 0:
        return False, 0, (p.stderr or "").strip()[:120]
    cred = dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l)
    tok = cred.get("password", "")
    return bool(tok), len(tok), cred.get("username", "")


def candidates(d, repo):
    """返回可能被提交的文件列表（相对路径）。"""
    if repo is not None:
        rc, out, _ = run(["git", "status", "--porcelain", "-uall"], cwd=d, timeout=30)
        if rc != 0:
            return []
        files = []
        for line in out.splitlines():
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            path = path.strip('"')
            if path:
                files.append(path)
        return files
    files = []
    for dp, dns, fns in os.walk(d):
        dns[:] = [x for x in dns if x not in BLOCK_DIRS and not x.startswith("_archive")]
        for fn in fns:
            files.append(os.path.relpath(os.path.join(dp, fn), d).replace("\\", "/"))
    return files


def scan(d, files):
    risks = []
    for rel in files:
        p = os.path.join(d, rel.replace("/", os.sep))
        parts = set(rel.split("/"))
        ext = os.path.splitext(rel)[1].lower()
        if any(p.startswith(("_archive", "_local_backup")) for p in parts):
            risks.append((rel, "位于本地备份目录"))
            continue
        if parts & BLOCK_DIRS:
            risks.append((rel, "位于不入库目录（%s）" % ",".join(parts & BLOCK_DIRS)))
            continue
        if ext in BLOCK_EXT or re.search(r"\.(bak\d*|db-(wal|shm))$", rel):
            risks.append((rel, "扩展名 %s 属于本地数据/运行文件" % (ext or rel)))
            continue
        if rel.startswith(".") and rel.endswith(".env"):
            risks.append((rel, "环境变量文件"))
            continue
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if size > BIG_BYTES:
            risks.append((rel, "体积 %.1f MB，确认是否为业务数据" % (size / 1048576.0)))
        if ext in {".json", ".md", ".txt", ".py", ".js", ".html", ".yml", ".yaml", ".sql"} and size <= BIG_BYTES:
            try:
                text = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if SECRET_RE.search(text):
                risks.append((rel, "疑似密钥/私钥"))
            if ABS_PATH_RE.search(text):
                risks.append((rel, "含个人绝对路径（C:\\Users\\...）"))
            if ext == ".json" and LONGNUM_RE.search(text):
                risks.append((rel, "JSON 里出现 12 位以上数字串，疑似账号/卡号"))
    return risks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--proxy", default="auto", help="auto 或 http://127.0.0.1:7897")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = os.path.abspath(a.repo_dir)

    report = {"dir": d, "problems": [], "warnings": [], "info": {}}
    gv = git_version()
    report["info"]["git"] = gv
    if not gv:
        report["problems"].append("找不到 git，请先安装 Git for Windows / git")

    repo = repo_state(d) if gv else None
    report["info"]["is_repo"] = bool(repo)
    if repo:
        report["info"].update({"branch": repo["branch"], "remote": repo["remote"].splitlines(),
                               "author": repo["author"], "dirty_lines": len(repo["dirty"].splitlines())})
    else:
        report["warnings"].append("目录不是 git 仓库：先 clone 目标仓库到临时目录，比对差异后按白名单同步，再建分支提交（不要 git init 后直接推）")

    direct = reachable("github.com", 443)
    api = reachable("api.github.com", 443)
    open_ports = [p for p in PROXY_CANDIDATES if reachable("127.0.0.1", p, 1.5)]
    # 以 git 实测为准：socket 能连通不代表 git 能连（DNS 解析可能不同）
    direct_git, direct_err = git_probe("") if gv else (False, [])
    proxy = None
    if a.proxy and a.proxy != "auto":
        proxy = a.proxy
        proxy_git, proxy_err = git_probe(proxy)
    elif direct_git:
        proxy, proxy_git, proxy_err = "", True, []
    else:
        proxy, proxy_git, proxy_err = None, False, []
        for port in open_ports:
            cand = "http://127.0.0.1:%d" % port
            ok, err = git_probe(cand)
            if ok:
                proxy, proxy_git, proxy_err = cand, True, []
                break
            proxy_err = err
    report["info"].update({"github_443": direct, "api_443": api, "listening_ports": open_ports,
                           "git_direct": direct_git, "git_direct_err": direct_err,
                           "proxy": proxy, "git_via_proxy": proxy_git, "proxy_err": proxy_err})
    if not proxy:
        report["problems"].append("git 连不上 github.com（直连与代理都不通）：%s" % (
            (direct_err or proxy_err or ["未知错误"])[0][:160]))

    ok, tlen, user = credential_ok()
    report["info"].update({"credential": ok, "credential_user": user, "token_len": tlen})
    if not ok:
        report["warnings"].append("没有可用的 GitHub 凭据：让用户完成一次登录（GCM 弹窗或 gh auth login），否则 push/开 PR 会失败")

    files = candidates(d, repo)
    report["info"]["candidate_count"] = len(files)
    risks = scan(d, files)
    report["risks"] = risks
    if risks:
        report["problems"].append("待提交文件中有 %d 项风险，先修 .gitignore 或移出提交范围" % len(risks))

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("== 体检 %s ==" % d)
        print("git           : %s" % (gv or "未安装"))
        print("是否 git 仓库 : %s" % ("是" if repo else "否"))
        if repo:
            print("当前分支      : %s" % repo["branch"])
            print("远程          : %s" % ("; ".join(repo["remote"].splitlines()) or "未配置"))
            print("最近提交作者  : %s" % repo["author"])
            print("未提交改动    : %d 行" % len(repo["dirty"].splitlines()))
        print("github.com:443: %s   api.github.com:443: %s（socket，仅供参考）" % (direct, api))
        print("git 直连      : %s" % ("通" if direct_git else "不通｜%s" % ((direct_err or ["-"])[0][:100])))
        print("本机代理端口  : %s" % (open_ports or "无"))
        print("将使用代理    : %s" % (proxy if proxy else "无可用通路"))
        print("凭据          : %s" % ("已授权（%s，令牌 %d 位）" % (user, tlen) if ok else "无"))
        print("待提交文件    : %d 个" % len(files))
        if risks:
            print("\n-- 风险项 --")
            for rel, why in risks:
                print("  ! %s  —— %s" % (rel, why))
        for w in report["warnings"]:
            print("\n提示：%s" % w)
        print("\n结论：%s" % ("可以继续" if not report["problems"] else "有阻塞项，先处理上面的问题"))
    return 0 if not report["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())