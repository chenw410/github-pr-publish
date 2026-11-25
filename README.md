# github-pr-publish · 上传 GitHub 并提 PR

把本地项目或一批改动安全地传到 GitHub：先体检，再同步，最后开 PR 并盯 CI。

## 装到本机

```bash
git clone <本仓库地址> ~/.agents/skills/github-pr-publish
# 或把整个目录复制到 ~/.agents/skills/github-pr-publish
```

技能目录结构：

```
github-pr-publish/
├── SKILL.md                    流程与判断（助手读这个）
├── README.md
├── meta.yaml
├── references/troubleshooting.md   代理、凭据、CI 日志、Windows 坑位
└── scripts/
    ├── preflight.py            环境 + 敏感数据体检
    ├── diff_tree.py            本地目录 vs 克隆仓库 三张差异清单
    ├── open_pr.py              没有 gh 时用已授权凭据调 API 开 PR
    └── ci_watch.py             等 CI，失败拉日志尾部
```

只依赖 Python 3.9+ 标准库与 git，不需要 `gh`、不需要 `pip install`。

## 三步走

```bash
# 1. 体检：git / 仓库 / 代理 / 凭据 / 待提交文件里的敏感项
python scripts/preflight.py --repo-dir .

# 2. 本地没有 .git 时：先比差异，再按白名单同步（远程更新的文件要保留）
python scripts/diff_tree.py . tmp/clone

# 3. 开 PR（已 push 分支之后）
python scripts/open_pr.py --repo owner/name --head feat/x --base main \
  --title "feat: ..." --body-file pr.md --proxy http://127.0.0.1:7897

# 4. 等 CI；失败自动打印 job 日志尾部
python scripts/ci_watch.py --repo owner/name --ref feat/x --proxy http://127.0.0.1:7897
```

## 它坚持的几件事

- 数据库、Excel、截图、`.env`、本地备份、绝对路径、疑似令牌，**不进提交**——体检拦下来先修 `.gitignore`。
- 远程比本地新（或远程独有）的文件**不覆盖、不删除**。
- 令牌只从 git 凭据里现取现用，不打印、不落盘。
- **不代用户点合并**，PR 开到「可合并」就交回。

## 环境前提

- git 已配置可用凭据（首次会触发 GitHub 登录窗口）：`git credential fill` 能返回 password。
- 本机直连 github.com 不通时，先找到本机代理端口再传给各脚本；细节见 `references/troubleshooting.md`。