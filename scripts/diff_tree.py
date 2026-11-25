#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diff_tree.py —— 比对两个目录，输出「只在本地 / 只在远程 / 内容不同」三张清单

用途：本地目录没有 .git 时，先 clone 目标仓库，再用它判断哪些文件该同步、
哪些远程已有的更新必须保留。

用法：
    python diff_tree.py <本地目录> <克隆目录>
    python diff_tree.py . tmp/clone --limit 0          # 全列，不截断
    python diff_tree.py . tmp/clone --keep-binary      # 连二进制也读内容比对
    python diff_tree.py . tmp/clone --exclude "*.mjs,dist"

默认跳过 .git / 依赖目录 / 临时目录 / 本地备份目录，输出每张清单只列前 40 条。
"""
import argparse
import fnmatch
import hashlib
import os
import sys

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".workbuddy", ".archify",
             ".codex", ".idea", ".pytest_cache", "tmp", "uploads", "backup", "dist"}
SKIP_PREFIX = ("_archive", "_local_backup")
SKIP_EXT = {".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".xlsx", ".xls", ".xlsm",
            ".csv", ".tsv", ".zip", ".png", ".jpg", ".jpeg", ".pdf", ".log", ".pid", ".pyc"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def walk(root, skip_binary, max_size, excludes):
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIX)]
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(fn, pat) for pat in excludes):
                continue
            ext = os.path.splitext(fn)[1].lower()
            try:
                size = os.path.getsize(p)
            except OSError:
                out[rel] = "err"
                continue
            if skip_binary and ext in SKIP_EXT:
                out[rel] = "bin:%d" % size
            elif max_size and size > max_size * 1024 * 1024:
                out[rel] = "big:%d" % size
            else:
                try:
                    out[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
                except OSError:
                    out[rel] = "err"
    return out


def show(title, keys, fmt, limit):
    print("\n== %s（%d）==" % (title, len(keys)))
    for k in keys[:limit] if limit else keys:
        print(fmt(k))
    if limit and len(keys) > limit:
        print("  … 还有 %d 条，用 --limit 0 全列" % (len(keys) - limit))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("local")
    ap.add_argument("remote")
    ap.add_argument("--keep-binary", action="store_true", help="二进制也读内容比对")
    ap.add_argument("--max-size", type=int, default=20, help="超过多少 MB 只比大小（默认 20）")
    ap.add_argument("--limit", type=int, default=40, help="每张清单最多列几条，0=全列")
    ap.add_argument("--exclude", default="", help="逗号分隔的 glob，如 \"*.mjs,dist/*\"")
    a = ap.parse_args()
    lo, ro = os.path.abspath(a.local), os.path.abspath(a.remote)
    for d in (lo, ro):
        if not os.path.isdir(d):
            print("目录不存在：%s" % d)
            return 2
    excludes = [x.strip() for x in a.exclude.split(",") if x.strip()]
    L = walk(lo, not a.keep_binary, a.max_size, excludes)
    R = walk(ro, not a.keep_binary, a.max_size, excludes)
    only_l = sorted(set(L) - set(R))
    only_r = sorted(set(R) - set(L))
    diff = sorted(k for k in set(L) & set(R)
                  if L[k] != R[k] and not str(L[k]).startswith(("bin:", "big:", "err")))

    print("本地 %s（%d 个文件） vs 远程 %s（%d 个文件）" % (lo, len(L), ro, len(R)))
    show("只在本地 —— 判断是否该入库", only_l, lambda k: "  + %-64s %s" % (k, L[k][:12]), a.limit)
    show("只在远程 —— 默认保留，不要因本地没有而删除", only_r, lambda k: "  - %s" % k, a.limit)
    show("内容不同 —— 先看谁更新，再定覆盖方向", diff, lambda k: "  ~ %s" % k, a.limit)
    print("\n提示：只用本地目录覆盖整份远程，会删掉「只在远程」的文件、回退别人的提交。"
          "「内容不同」的每条都先用 git diff --no-index 看过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())