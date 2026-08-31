# 部署文档

> 本文件记录 gpx2mbtiles 在云服务器的完整部署方案：架构、代理、自愈、安全加固、自动化部署与运维命令。
> 适用范围：个人自用部署（阿里云 ECS · Alibaba Cloud Linux 3 · 墙内网络）。

## 1. 架构总览

```
公网浏览器 ──▶ 阿里云安全组(入:80,22022) ──▶ Caddy :80 ──▶ gpx2mbtiles 容器 127.0.0.1:8000
                                                          │
  瓦片下载(容器) ── TILE_PROXY=host.docker.internal:7893 ──▶ mihomo 代理(宿主机) ──▶ 瓦片源(Windy/OpenTopoMap)
  Docker 拉镜像 ── daemon.json proxies ─────────────────────▶ mihomo 代理 ──▶ Docker Hub(镜像加速)
  git fetch(自动部署) ── git http.proxy ─────────────────────▶ mihomo 代理 ──▶ github.com
```

**代理边界（用户明确要求）**：只有受限地址（瓦片源、Docker Hub、GitHub）走 mihomo 代理；**Web 服务本身不走代理**（Caddy 直接反代容器，无代理层）。

## 2. 服务器环境

| 项 | 值 |
|---|---|
| 云厂商 / 机型 | 阿里云 ECS 轻量应用服务器（墙内） |
| 公网 IP | `59.110.15.156` |
| 系统 | Alibaba Cloud Linux 3（RHEL 系，yum 包管理） |
| 规格 | 2 核 / 1.8G 内存 / 40G 磁盘 |
| SSH | `root@59.110.15.156 -p 22022`（**默认 22 已关闭**） |
| 应用目录 | `/opt/gpx2mbtiles`（git 仓库，含 .env / compose.yaml / app / web / scripts） |
| 数据目录 | `/opt/gpx2mbtiles/data`（SQLite 账本 + 成品，挂载进容器，chown 10001:10001） |

## 3. 端口与安全组

| 端口 | 用途 | 暴露范围 |
|---|---|---|
| 80 | HTTP Web（Caddy 反代） | 公网（安全组入方向放行） |
| 22022 | SSH | 公网（安全组入方向放行；22 已从 sshd 移除） |
| 8000 | 应用 API（容器内） | 仅 127.0.0.1 回环，不对外 |
| 7893 | mihomo 混合代理 | 仅 127.0.0.1 + Docker 网桥 172.17.0.0/16（iptables 收紧，外部 REJECT） |

安全组只需放行入方向 **80、22022**（出方向默认全放行）。

## 4. 服务组件

| 服务 | 实现 | 启动方式 | 配置 |
|---|---|---|---|
| Web 应用 | Docker 容器 `gpx2mbtiles` | docker compose（restart=unless-stopped） | `/opt/gpx2mbtiles/compose.yaml` + `.env` |
| 反向代理 | Caddy v2 | systemd `caddy.service` | `/etc/caddy/Caddyfile`（`:80 → reverse_proxy 127.0.0.1:8000`） |
| 代理 | mihomo v1.19.30 | systemd `mihomo.service` | `/etc/mihomo/config.yaml`（订阅处理产物） |
| 订阅更新 | python 脚本 + cron | crond（每小时） | `/opt/gpx2mbtiles/scripts/update_sub.py` |

## 5. 代理方案（mihomo）

**背景**：服务器在墙内，Windy 瓦片源 / Docker Hub / github.com 全部不可直连（实测 timeout）。因此引入 mihomo + 机场订阅做出口。

- **订阅链接**：`https://sub.bwbwbw.cc/406016/...`（服务器可直连；请求带 UA `clash.meta` 返回完整 mihomo 配置，47 节点）
- **混合端口**：mixed-port `7893`（HTTP + SOCKS5 同端口）
- **订阅自动更新**：cron `0 * * * *` 每小时执行 `update_sub.py --commit`：
  1. 下载最新订阅配置
  2. 将 `Proxies` 节点组改为 `url-test`（每 300s 自动测速，选最优可用节点）
  3. 在 rules 顶部注入强制走代理域名：`DOMAIN-SUFFIX,windy.com,Proxies`、`DOMAIN-SUFFIX,opentopomap.org,Proxies`
  4. `mihomo -t` 校验 → 覆盖 `/etc/mihomo/config.yaml` → 重启 mihomo
- **Docker 镜像加速**：`/etc/docker/daemon.json` 配置
  - `registry-mirrors: ["https://docker.m.daocloud.io"]`（实测唯一可达的国内镜像）
  - `proxies.http/https: http://127.0.0.1:7893`（拉镜像也走代理，no-proxy 含本机/内网）
- **容器访问宿主机代理**：compose 配置 `extra_hosts: host.docker.internal:host-gateway`，应用 `.env` 中 `TILE_PROXY=http://host.docker.internal:7893`

> ⚠️ 依赖关系：瓦片下载依赖 mihomo。mihomo 挂了 → 瓦片源不可达 → 任务失败。重启 mihomo 后会自动恢复（无状态）。

## 6. 应用配置

`.env`（`/opt/gpx2mbtiles/.env`，参考 `.env.example`）关键项：

| 变量 | 部署值 | 说明 |
|---|---|---|
| `AUTH_TOKEN` | **在 .env 中设置**（所有 `/api/*` 需 `X-API-Key` 头或 URL `?token=` 参数；`/api/health` 免鉴权） | 请勿明文提交到 git |
| `TILE_PROXY` | `http://host.docker.internal:7893` | 走 mihomo |
| `TILE_URL_TEMPLATE` | `https://tiles.windy.com/v1/maptiles/outdoor/256/{z}/{x}/{y}/?lang=en` | Windy Outdoor |
| `MAX_CONCURRENCY` / `REQUEST_INTERVAL_MS` | `8` / `100` | 限流 |
| `MAX_RUNNING_TASKS` / `MAX_TILES_PER_TASK` | `2` / `60000` | 资源保护 |
| `TASK_TIMEOUT_SECONDS` / `FILE_EXPIRY_SECONDS` | `3600` / `259200` | 超时与过期 |

其他：
- `compose.yaml`：`127.0.0.1:8000:8000`（不对外）、`extra_hosts` host-gateway、`./data:/app/data`、`restart: unless-stopped`
- `Dockerfile`：pip 使用腾讯云 PyPI 镜像（`mirrors.cloud.tencent.com`），非 root 用户 uid 10001
- 瓦片图层：`app/config.py` 注册 `windy`（默认，max_zoom 18）与 `opentopomap`（OpenTopoMap 地形图，a/b/c 子域名轮询，max_zoom 17）

## 7. 重启自愈

- **systemd 全部 enable**：`sshd / fail2ban / iptables / docker / caddy / mihomo / crond`
- **容器** `restart: unless-stopped`：docker 重启后自动拉起
- **任务账本** SQLite 持久化（`data/tasks.db`），重启后任务状态不丢
- **已用真实 `reboot` 验证**：重启后各组件自动恢复、订阅配置生效、瓦片下载可用

## 8. 安全加固

| 措施 | 配置 |
|---|---|
| SSH 端口 | `22022`（sshd_config `Port 22022`；SELinux Disabled，无需 semanage） |
| fail2ban | 5 次密码失败封禁 1 小时（jail `sshd`，`/etc/fail2ban/jail.local`，ignoreip 含 127.0.0.1/172.17.0.0/16） |
| iptables | `/root/harden_iptables.sh`（持久化 `/etc/sysconfig/iptables` + iptables service）：放行 22022/80，7893 仅限 127.0.0.1 + 172.17.0.0/16，其余 REJECT |
| 密码登录 | **当前为 root 密码登录（未配 SSH 密钥）**。若仓库公开或有协作者，建议改用密钥登录并禁用密码 |

> 加固命令文件在服务器 `/root/harden_iptables.sh`，修改后需 `iptables-save > /etc/sysconfig/iptables` 持久化。

## 9. 自动部署（GitHub Actions）

Workflow：`.github/workflows/deploy.yml`（`Deploy on Tag`）

- **触发**：推送 `v*` tag；或仓库 Actions 页面手动 **Run workflow**（`workflow_dispatch`）
- **Secrets**（仓库 Settings → Secrets and variables → Actions）：
  - `SSH_HOST`（公网 IP）、`SSH_USER`（root）、`SSH_PASSWORD`（SSH 密码，注意含特殊字符，复制粘贴）
- **流程**（appleboy/ssh-action，port 22022）：
  1. 服务器 `/opt/gpx2mbtiles` `git fetch --tags`（服务器 git 已配置 `http.proxy=http://127.0.0.1:7893` 走代理）
  2. `git checkout <tag>`（手动触发时用 `origin/main`）
  3. `docker compose build --pull` → `up -d`
  4. 健康检查 `/api/health`（最多 60s）
  5. 失败 → 自动回滚到 `.last_success` 记录的上一成功 tag，并重新健康检查
- **状态记录**：成功 tag 写入 `/opt/gpx2mbtiles/.last_success`

## 10. 运维常用命令

```bash
# SSH（22022）
ssh root@59.110.15.156 -p 22022

# 服务状态
systemctl is-active caddy mihomo fail2ban docker crond
docker ps                                   # 容器
docker logs --tail 50 gpx2mbtiles           # 应用日志
journalctl -u mihomo -n 50                  # 代理日志
tail -20 /var/log/mihomo_update.log         # 订阅更新日志
fail2ban-client status sshd                 # 被封 IP

# 手动更新订阅并生效
/usr/bin/python3 /opt/gpx2mbtiles/scripts/update_sub.py --commit

# 手动部署（与 workflow 等价）
cd /opt/gpx2mbtiles && docker compose up -d --build

# 数据目录（含任务账本与成品）
ls /opt/gpx2mbtiles/data/
```

**本机部署工具**（`L:\Projects\gpx2mbtiles\.deploy\`，paramiko 脚本，SSH 端口 22022）：
- `ssh_run.py "<cmd>"`：远程执行命令
- `update_sub.py`：本地源（与服务器 scripts/ 同源）
- `check_state.py` / `check_security.py`：状态与安全检查
- `deploy_v2.py`：上传代码 + 更新代理规则 + 重建容器

> ⚠️ `.deploy/` 内脚本硬编码服务器密码，已通过 `.gitignore` 排除，**禁止提交到 git**。

## 11. 已知限制与注意

1. **无 HTTPS**：服务器仅 HTTP（:80）。纯 IP 无法申请免费 TLS 证书（Let's Encrypt 需要域名）。影响：**iOS Safari 无法直接保存下载的 .mbtiles 到「文件」App**（需配合其他方式或上 HTTPS/域名）。Android/PC 浏览器一般可下载。
2. **强依赖 mihomo**：瓦片下载、Docker 拉镜像、git fetch 均走本地 7893 代理；mihomo 不可用时相关功能全部失败。
3. **订阅每小时更新**：机场订阅若变更节点/规则，最多 1 小时内自动同步；更新失败（如订阅链接失效）时 mihomo 保持旧配置运行（`update_sub.py` 校验失败不会覆盖）。
4. **个人自用合规**：Windy-Outdoor 服务条款禁止批量爬取瓦片，已启用限流与请求间隔，不得对外提供服务。

## 12. 部署历史

| 日期 | 变更 |
|---|---|
| 2026-08-31 | 首次部署：Docker 容器 + mihomo 代理 + 每小时订阅更新 + Caddy :80 + 重启自愈 + SSH 22022 + fail2ban/iptables 加固 + GitHub Actions 自动部署 |
| 2026-08-31 | 新增 OpenTopoMap 地形图图层 + 自定义文件名；下载鉴权支持 URL `?token=`（iOS 原生下载兼容） |
