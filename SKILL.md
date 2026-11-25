---
name: github-pr-publish
label: 上传 GitHub 并提 PR
description: 把本地项目或一批改动安全地传到 GitHub 并开 PR/直接推主干。覆盖本机直连 github.com 不通时的代理探测、敏感文件与凭据体检、本地没有 .git 时的白名单同步、未安装 gh 时用已授权凭据调 API 开 PR、以及 CI 失败日志定位。适用场景：用户说"传到 GitHub""提个 PR""推到我的仓库""帮我上传这个项目"，或本机没有 gh、github.com 连接超时、仓库尚未初始化、远程已有他人更新的文件需要保留。
---

# 上传 GitHub 并提 PR

把「本地改动 → 远程分支 → PR」这条路走完，并在每一步留下可核对的证据（跑了什么命令、退出码、看到什么）。**不做**两件事：不代用户点合并；不为了跑通而把敏感文件、令牌或本地数据带上去。

## 三条铁律

1. **先体检再 add。** 数据库、Excel、截图、`.env`、本地备份、绝对路径、疑似令牌，任何一项命中就停下修 `.gitignore`，不要先提交再删。
2. **远端已有的更新不能覆盖。** 本地目录往往比远程旧（或远程有别人的新提交）。同步前必须逐文件比对，远程更新的、远程独有的都保留。
3. **令牌只进内存。** 需要 API 认证时用 `git credential fill` 现取现用，不打印、不写文件、不进提交、不回显到日志。

## 第一步：体检

```bash
python scripts/preflight.py --repo-dir <项目目录>
```

它会报告：git 是否可用、是否已是 git 仓库、当前分支与 remote、`github.com:443` 直连是否通、本机在监听哪些常见代理端口、`git credential fill` 是否已有可用凭据（只报长度）、以及**当前将被提交的文件里有没有敏感项**。退出码 1 表示有阻塞项，先按提示处理。

体检结果决定后面走哪条路：

| 情况 | 处理 |
|---|---|
| 直连不通、本机有 7890/7897/10809 等端口在听 | 后续所有 git 命令加 `-c http.proxy=http://127.0.0.1:<port>`，**不要**改全局配置 |
| `nslookup github.com` 与 git 报的 IP 不一致 | 典型的 DNS 污染；以能否连通为准，不要怀疑仓库地址写错 |
| 目录没有 `.git` | 不要 `git init` 后直接推——先 `git clone <repo> <tmp目录>`（浅克隆即可），比对差异后把本地文件按白名单同步进去，在克隆里建分支提交（见第三步） |
| 有 `.git` 但 remote 不是目标仓库 | 先 `git remote -v` 核对，必要时 `git remote set-url`，不要盲目 push |
| 凭据为空 | 停下让用户完成一次 GitHub 登录（GCM 弹窗或 `gh auth login`），不要索取密码或让用户把 token 贴到对话里 |

## 第二步：敏感数据体检的标准

`.gitignore` 至少覆盖：`*.db` `*.db-*` `*.sqlite*` `*.xlsx` `*.xls*` `*.csv` `*.png` `*.jpg` `*.pdf` `*.zip` `uploads/` `tmp/` `.venv/` `*.log` `*.bak*` `.env*`，以及**项目自己的业务数据文件**（例如本地种子 `seed.json`、工作库、上传原件目录）。

再补三条脚本查不出的判断：

- **体积与用途**：几 MB 的 JSON/HTML 若含业务记录（账户号、金额、客户名），不入库；纯规则字典（科目、规则、关键词）可以入库。
- **生成物**：构建产物是否入库按项目约定；若入库，必须与源码同一次提交，避免「源码改了产物没改」。
- **调试残留**：`probe*.mjs`、`test_ui*.mjs`、`*.bak7`、误重定向产生的空文件（如同名于报错片段的怪文件名），一律不进提交，必要时补 `.gitignore` 规则而不是靠人工记。

提交前确认一次：

```bash
git add -A && git status --short      # 逐行看，出现 db/xlsx/mjs 就退回
git diff --cached --stat
```

## 第三步：本地没有 `.git` 时的安全同步

```bash
git clone --depth 20 <repo> <tmp>/clone          # 加代理则 -c http.proxy=...
python scripts/diff_tree.py <本地目录> <tmp>/clone  # 新增/删除/内容不同 三张清单
```

处理规则：

- **只在本地有**：判断是否该入库（源码、文档、产物）→ 复制；调试脚本、备份、业务数据 → 跳过。
- **只在远程有**：默认保留，绝不因「本地没有」而删除。
- **两边都有但不同**：先 `git diff --no-index` 看谁更新。远程更完整的文档/测试（如别人补的 user-guide、harness）保留远程；本地演进的源码覆盖。只比 hash 就覆盖会丢掉别人的提交。

复制后：

```bash
cd <tmp>/clone
git checkout -b feat/<topic>-<yyyymmdd>
git config user.name "<仓库历史作者>"; git config user.email "<其邮箱>"
```

提交身份优先取 `git log -3 --pretty="%an | %ae"` 里的仓库作者，保持一致；用户明确要求用自己的身份时再换。

## 第四步：提交与推送

提交信息用文件传，避免多行被 shell 截断（cmd.exe 会在第一个换行处静默截断）：

```bash
git commit -F <消息文件>          # 首行 <= 50 字概述，空行后分点写"做了什么/为什么/验证"
git -c http.proxy=http://127.0.0.1:7897 push -u origin feat/<topic>-<yyyymmdd>
```

推送成功时远程会回一行 `Create a pull request ... by visiting: <链接>`，把它记下来。

## 第五步：开 PR（没有 gh 也行）

先看有没有 `gh`：`where gh` / `command -v gh`。有就用 `gh pr create`；没有就走 API：

```bash
python scripts/open_pr.py --repo <owner>/<name> --head feat/<topic> --base main \
  --title "..." --body-file <PR正文.md> [--proxy http://127.0.0.1:7897]
```

脚本内部：`git credential fill` 取凭据 → `POST /repos/{owner}/{repo}/pulls` → 打印 PR 链接，令牌不落盘。

PR 正文写四块：**这次提交了什么**（按目录/模块分点）、**为什么**、**怎么验证的**（具体命令与结果，不是"已测试"）、**没有带上去的内容**（数据文件、密钥）。让 reviewer 不必翻 diff 就能判断。

## 第六步：盯 CI，失败要定位到步骤

```bash
python scripts/ci_watch.py --repo <owner>/<name> --ref <分支> [--proxy ...]
```

全部通过才算交付。失败时它会把 job 日志尾部拉下来（GitHub 的日志接口 302 到 Blob 存储，**跟随时不能带 Authorization**，否则 401）。

常见失败与处理：

| 现象 | 原因 | 处理 |
|---|---|---|
| 发布检查类脚本报「缺少可核对的页面初始数据」 | 仓库的数据体检脚本只认某几个 HTML 的内嵌 `const DATA` | 扩展脚本：内嵌数据的页面走原检查，改为接口取数的页面做**反向**检查（不得内嵌业务记录），不要为新页面伪造 `DATA` |
| `git diff --exit-code` 有差异 | 提交了源码却没重建产物，或产物重建后没提交 | 重建 + 一起提交 |
| 测试找不到文件/路径 | 测试依赖本机路径或未入库的数据 | 让测试自建临时数据；不要把工作库搬进仓库 |
| 只在某个平台失败 | 行尾、路径分隔符、编码 | 显式指定 encoding/换行；断言里不要写盘符路径 |

## 交付话术

给出：PR 链接、分支名、文件数与增删行、CI 结论（哪些 job、什么平台）、**明确说明没有代合并**、以及没提交什么和为什么。若推的是新建仓库，说明仓库归属与可见性，并提示改名/迁移方式。

## 参考

- `references/troubleshooting.md`：代理、凭据、302 日志、行尾、编码、cmd 截断等实测坑位与命令。
- `scripts/`：`preflight.py`（体检）、`diff_tree.py`（比目录）、`open_pr.py`（开 PR）、`ci_watch.py`（等 CI 并拉失败日志）。