# 实测坑位与命令速查

本文件是在 Windows + Git 2.52 + 无 `gh` CLI、github.com 直连不通的环境里跑通「提交 → 推送 → 开 PR → 等 CI」后整理的。命令均可直接复制。

## 1. 连不上 github.com

```bash
git ls-remote https://github.com/<owner>/<repo>     # 观察报错
nslookup github.com                                 # 系统 DNS 结果
```

- `Failed to connect to github.com port 443 after 21xxx ms` 而 `api.github.com:443`、`ssh.github.com:443` 可达 → 是解析/出口问题，不是仓库地址错。
- 系统 `nslookup` 给出的 IP 与 git 报错里的 IP 不一致 → DNS 污染或被内网 DNS 改写。

先找本机代理端口（Clash/Mihomo 常见 7890、7897；v2ray 10808、10809）：

```bash
netstat -ano | findstr LISTENING | findstr /r ":7890 :7897 :1080 :10809 :8080 :3128"
```

用它，且**只对本次命令生效**，不要写进全局配置：

```bash
git -c http.proxy=http://127.0.0.1:7897 ls-remote https://github.com/<owner>/<repo>
git -c http.proxy=http://127.0.0.1:7897 clone --depth 20 https://github.com/<owner>/<repo> tmp/clone
git -c http.proxy=http://127.0.0.1:7897 push -u origin feat/x
```

Python 里调 API 同样要显式走代理：

```python
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": "http://127.0.0.1:7897"}))
```

## 2. 没有 gh CLI 时怎么开 PR

GitHub 在 push 成功后会回一行 `Create a pull request ... by visiting: <链接>`，可直接给用户；要自动化就调 API：

- 凭据来源：`git credential fill`（GCM 存在 Windows 凭据管理器里的授权）。传 `protocol=https\nhost=github.com\n` 到 stdin，读 `username`/`password`。
- 必须设 `GIT_TERMINAL_PROMPT=0` 与 `GCM_INTERACTIVE=never`，否则可能弹窗挂住。
- 端点：`POST https://api.github.com/repos/{owner}/{repo}/pulls`，Header `Authorization: Bearer <token>`、`Accept: application/vnd.github+json`。
- 常见返回：`401` 令牌失效；`404` 仓库/分支不存在或无权；`422` 分支无新提交、head==base、或同名 PR 已存在（此时用 `GET /repos/{o}/{r}/pulls?head={owner}:{branch}&state=open` 捞已有链接）。
- 想看令牌权限范围：`GET /user` 的响应头 `x-oauth-scopes`（常见 `repo, workflow, gist`）。**不要把令牌打印出来**。

## 3. CI 日志为什么 401

`GET /repos/{o}/{r}/actions/jobs/{job_id}/logs` 会 302 到 Azure Blob 的预签名地址。跟随时如果继续带 `Authorization`，Blob 侧会返回 `InvalidAuthenticationInfo`。正确做法：禁止自动重定向，拿到 `Location` 后**不带认证头**再请求一次。

```python
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None
```

## 4. 发布检查脚本常见拦截

仓库里常有一个 `scripts/check_release.py` 这类脚本，扫所有 tracked 文件，命中即失败：

| 报错 | 含义 | 正确改法 |
|---|---|---|
| `缺少可核对的页面初始数据: xxx.html` | 脚本要求每个 HTML 都有内嵌 `const DATA = {...}` | 把这类检查限定在**内嵌数据**的页面；从接口取数的页面改成反向检查（不得内嵌业务记录），不要为了过检伪造 `DATA` |
| `页面含业务记录 xxx` | 产物里带了真实流水/预算 | 重新构建产物，把数据 seed 移出仓库 |
| `个人绝对路径` | 文件里出现 `C:\Users\...` | 改成相对路径或环境变量 |
| `禁止发布本地数据或运行文件` | db/xlsx/截图/日志进了提交 | 补 `.gitignore` 并从索引移除：`git rm --cached <path>` |

本地先跑一遍再推，比推完等 CI 快：

```bash
python scripts/check_release.py    # 有的脚本要求先 git add
```

## 5. Windows 命令行的坑

- **cmd.exe 会把多行命令在第一个换行处静默截断**：多行一律写成 `.py`/`.ps1` 文件，或用 `&` 串成一行。
- `timeout /t 3 >nul` 在重定向 stdin 的环境里直接报「不支持输入重新定向」；改用 `powershell -NoProfile -Command "Start-Sleep -Seconds 3"`。
- 中文输出乱码：先 `chcp 65001` 并 `set PYTHONIOENCODING=utf-8`；Python 脚本里再 `sys.stdout.reconfigure(encoding="utf-8")`。
- `git commit -m "多行"` 会被截断：把信息写进文件，`git commit -F msg.txt`。
- 后台起服务：`powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath '<python>' -ArgumentList '<script>','--port','8770' -WorkingDirectory '<dir>'"`，用 `Test-NetConnection 127.0.0.1 -Port 8770` 确认。

## 6. 行尾与编码

- 仓库有 `.gitattributes` 时，git 会按属性归一化；克隆出来的工作区可能与你本地不同（CRLF/LF）。提交时出现 `LF will be replaced by CRLF` 的 warning 属正常。
- 项目自己要求固定行尾的（例如某文件必须 CRLF），改写后校验：`s.count("\n") - s.count("\r\n") == 0`。
- 中文文本文件被 GBK 写过会变成「鏈湴」这类乱码：发现即改回 UTF-8，别把乱码提交上去。

## 7. 本地没有 .git，但目录里有重要文件

不要 `git init` 后 `push --force`。正确顺序：

```bash
git clone --depth 20 <repo> tmp/clone
python scripts/diff_tree.py <本地目录> tmp/clone
# 按三张清单决定：只本地的挑着复制、只远程的保留、都有的先 diff 再定
cp -r <选定文件> tmp/clone/
cd tmp/clone && git checkout -b feat/<topic>-<yyyymmdd>
```

远程可能比你新（别人补的文档、测试）。用 `git diff --no-index <本地文件> <克隆文件>` 看内容，不要只看大小或时间戳。