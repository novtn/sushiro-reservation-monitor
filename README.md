# sushiro-skill

寿司郎（Sushiro）门店与实时预订余位查询，打包成一个 Agent Skill，也是一个独立可用的命令行工具。

数据来自寿司郎微信小程序自己的接口，只读：不代订、不取消、不改任何账户状态。

## 装成 skill

把整个目录放进你的 skills 目录，例如：

```bash
git clone https://github.com/novtn/sushiro-reservation-monitor.git ~/.dsh/skills/sushiro
```

`SKILL.md` 是给 agent 读的说明，`stores.csv` 是随包的门店清单快照（159 家），`config.example.json` 是待填的配置模板。

两样东西要你自己准备：抓一次 `auth_token`（见下文「先准备 token」，不抓连门店都查不了）；签名密钥只有 `cities` 和 `login` 用得上，见「签名密钥」，**不填也能查余位**。

## 或者当普通 CLI 用

```bash
uv run --project . sushiro cities
uv run --project . sushiro stores --city 上海
uv run --project . sushiro store 3025
uv run --project . sushiro slots --store 3025 --days 3
```

首次运行 uv 会自动建 `.venv` 并装 `cryptography`，十几秒。需要 Python 3.11+。

## 先准备 token

所有业务接口都要 `auth_token`：这是微信小程序的会话 JWT，**有效期 60 分钟，只能从你本人的微信里抓**。没有共享 token 这回事，也不能离线生成。

```bash
uv sync --extra capture     # 装 mitmproxy
uv run sushiro capture      # 监听 0.0.0.0:8888，打印手机该设的代理地址
```

手机连同一 Wi-Fi，HTTP 代理指向电脑的 8888，浏览器打开 `mitm.it` 装 CA 证书。**iOS 还要去 设置 → 通用 → 关于本机 → 证书信任设置 打开 mitmproxy 开关**，这一步漏了会一直报「网络状况不佳」。然后在手机上打开一次寿司郎小程序，token 自动写入并被后续命令复用。

也可以手动贴：

```bash
SUSHIRO_TOKEN=<jwt> uv run --project . sushiro slots --store 3025
```

## 输出长什么样

```
$ uv run --project . sushiro slots --store 3025 --days 2
门店 3025 · 2026-11-05 → 2026-11-06 · 可约 18/69 段
2026-11-05   5/27  14:45 15:30 15:45 21:00 21:15
2026-11-06  13/42  11:15 13:45 14:00 ...
```

每行是「日期 可约/总数 可约时段起点」。加 `--all` 连不可约时段一起列，加 `--json` 出机器可读结构。

## 命令

| 命令 | 说明 |
| --- | --- |
| `sushiro cities` | 城市列表 |
| `sushiro stores [--city 上海] [--open-only] [--limit N]` | 门店列表 |
| `sushiro store <id>` | 单店详情：地址、营业状态、排队桌数、可约人数区间 |
| `sushiro slots --store <id> [--date 11-08] [--days N] [--all] [--json]` | 预订时段 |
| `sushiro config` | 数据目录、token 是否过期 |
| `sushiro capture [--port 8888]` | 抓包刷新 token |

## 签名密钥（只有 cities / login 用）

**查余位不需要密钥**。`stores`、`store`、`slots` 只认 token，拿到 token 就能跑，不填任何密钥也正常。

只有 `cities` 和 `login` 要签名，而签名密钥是逆向得来的常量，**本仓库不提供，要自己填**：

1. 解包你自己手机上的小程序，在 `app-service.js` 里找 HMAC 密钥（64 字节字符串）、AES key（32 字节）和 iv（16 字节）。抓包拿不到，它们只在客户端本地参与计算。
2. 复制本目录的 `config.example.json` 为 `config.json`（放进数据目录），填上三个空位：

```json
{
  "auth_token": "<抓包得到的 JWT>",
  "sign_key": "<64 字节>",
  "aes_key": "<32 字节>",
  "aes_iv": "<16 字节>"
}
```

或走环境变量：`SUSHIRO_SIGN_KEY` / `SUSHIRO_AES_KEY` / `SUSHIRO_AES_IV`。

不填的后果：`cities` 报 `缺少 sign_key，签名请求需要它`，`login` 报缺 aes，其余命令照常。`sushiro config` 显示当前是否配齐。

顺便一提：实测服务端**并不校验** `X-App-Code` 头。带、不带、乱填都一样返回 200，所以 AES 那两个值只影响 `login` 的协议完整性。

## 环境

只在 **Windows 10（10.0.19045）+ Python 3.11.11 + uv 0.12.0** 上验证过。`cryptography` 本身跨平台，Linux / macOS 理论可用，但没实测，遇到问题不保证能修。

## 边界

只实现了官方 API 的 5 个端点：`citys`、`initialize`、`stores`、`getStoreById`、`store/timeslots`。

`js_code` 由微信签发、一次性、5 分钟有效，无法离线生成；JWT 也没法伪造——服务端密钥不在客户端包里。所以 token 只能抓，不能造。

接口限流 60 次/分钟，客户端内置 0.3 秒间隔和 429 退避。

排期按天滚动放号，靠后日期可能只放了一部分时段，别把「最后一天只有上午」当成订满。

## 注意

- 个人自用工具，与寿司郎官方无关。
- 抓包会解密你自己手机的流量，证书别乱装、别外传。
- 门店清单是打包时的快照，新店开业后会过时，实时列表用 `sushiro stores`。

## License

MIT，见 `LICENSE`。代码按原样提供，不担保可用；它调的是寿司郎自己的接口，那些服务条款怎么解释由你自己判断。
