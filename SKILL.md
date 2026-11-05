---
name: sushiro
description: 查询寿司郎（Sushiro）门店信息与实时预订余位，数据来自寿司郎微信小程序官方 API。当用户问某家门店有没有位置、某天能不能订、几点可以约、门店是否营业、现场排队几桌、有哪些城市/门店，或需要抓取/刷新 auth_token 时使用。只读，不代订、不取消。
---

# 寿司郎余位查询

只读客户端：城市、门店、门店详情、预订时段。auth_token 来自用户本人微信会话，约 60 分钟过期。

## 运行

```bash
uv run --project <SKILL_DIR> sushiro <命令>
```

`<SKILL_DIR>` 是本 skill 目录（含 `pyproject.toml`）。首次运行 uv 会自动建 `.venv` 并装 `cryptography`，约十几秒。

如果项目目录已存在（里面有 `config.json` 和 token），优先复用：

```bash
SUSHIRO_HOME=<项目目录> uv run --project <SKILL_DIR> sushiro slots --store 3025
```

数据目录解析顺序：`--data-dir` → `$SUSHIRO_HOME` → 当前目录有 `config.json` 就用当前目录 → `~/.sushiro`。

## 签名密钥

**查余位不需要密钥**。`stores` / `store` / `slots` 走 gateway 命名空间，只认 Bearer token，拿到就能用。

只有两个命令要签名密钥：

| 命令 | 需要 |
| --- | --- |
| `stores` / `store` / `slots` | 仅 auth_token |
| `cities` | + `sign_key` |
| `login` | + `sign_key`、`aes_key`、`aes_iv`（仅探测用） |

密钥是逆向常量，不随本仓库分发。取值：解包自己手机上的寿司郎小程序，在 `app-service.js` 里找 HMAC 密钥（64 字节字符串）与 AES key/iv。抓包抓不到——它们只在客户端本地参与计算，网络上看不到。

配置方式二选一：

```bash
export SUSHIRO_SIGN_KEY=<64字节>
export SUSHIRO_AES_KEY=<32字节>
export SUSHIRO_AES_IV=<16字节>
```

```json
{"sign_key": "...", "aes_key": "...", "aes_iv": "..."}
```

写进数据目录的 `config.json`。`sushiro config` 会显示 `sign_key: True/False`、`aes_keys: True/False`。

## 命令

```bash
sushiro cities                          # 31 个城市
sushiro stores --city 上海               # 按城市名过滤（子串匹配 name/nameKana）
sushiro stores --open-only --limit 20    # 只看营业中的
sushiro store 3025                       # 单店详情：地址、营业状态、排队桌数、可约人数
sushiro slots --store 3025               # 全部排期（约 30 天，1274 段）
sushiro slots --store 3025 --days 3      # 今天起 3 天
sushiro slots --store 3025 --date 11-08  # 单日：2026-11-08 或 20261108
sushiro slots --store 3025 --persons 4   # 人数（实测对 3025 无区分度）
sushiro slots --store 3025 --json        # 机器可读
sushiro config                           # 看数据目录、token 是否存在/过期
```

`slots` 输出：

```
门店 3025 · 2026-11-05 → 2026-12-05 · 可约 921/1274 段
2026-11-05   5/27  14:45 15:30 15:45 21:00 21:15
2026-11-06  13/42  11:15 13:45 14:00 ...
```

每行 `日期  可约/总数  可约时段起点`。`--all` 追加列出不可约时段。

## 门店清单

`stores.csv`（同目录）是打包时的全量快照：**2026-11-05 · 159 家 · 28 个城市**。只有三列：

```
id,area,name
3025,上海普陀区,上海环球港店
3026,上海长宁区,中山公园龙之梦店
```

`area` 是服务端返回的行政区，自带城市前缀（`上海普陀区`、`北京朝阳区`），按它就能认出城市，不必再查城市表。用途是在不联网、或不想多打一次接口时先把门店名对上 ID：

```bash
grep 环球港 stores.csv     # → 3025,上海普陀区,上海环球港店
uv run --project <SKILL_DIR> sushiro slots --store 3025
```

这份清单会过时（新店开业、闭店调改）。要最新列表跑 `sushiro stores`，那是实时请求，需要有效 token。

## token 过期

报错 `auth_token expired at ...` 时，用抓包刷新：

```bash
uv sync --extra capture     # 在 skill 目录装 mitmproxy
uv run sushiro capture      # 监听 0.0.0.0:8888，打印手机应设的代理地址
```

手机 Wi-Fi 设 HTTP 代理指向本机 8888，浏览器打开 `mitm.it` 装 CA，**iOS 还要在 设置→通用→关于本机→证书信任设置 打开开关**，然后打开寿司郎小程序一次。addon 自动把新 token 写进数据目录并更新 `config.json`。

也可以手动贴：

```bash
SUSHIRO_TOKEN=<jwt> uv run --project <SKILL_DIR> sushiro slots --store 3025
```

## 约束

- `js_code` 由微信签发、一次性、5 分钟有效，无法离线生成；不要尝试伪造 token，服务端密钥不在客户端包内。
- 只实现 5 个官方文档端点（`citys`、`initialize`、`stores`、`getStoreById`、`store/timeslots`）。其余 45 个未文档化端点不在范围内。
- 限流 60 次/分钟，客户端已内置 0.3s 间隔与 429 退避。
- 门店 ID 在 `stores` 响应里叫 `id`，在 `timeslots` 响应里叫 `storeId`。
- 时段字段：`date=20261105`、`start=111500`、`availability=AVAILABLE|UNAVAILABLE`；CLI 已转成 `2026-11-05` / `11:15`。
- 预约排期按天滚动放号，靠后日期可能只放了一部分时段（例如最后一天只有上午），不要当成"订满"。
