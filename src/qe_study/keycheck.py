"""Read-only audit of an exchange API key's permissions.

One request per exchange, no order calls, no fund movement. The key is never
printed, logged or written to disk: the snapshot below only carries booleans
derived from the permissions endpoint.

    python run.py keycheck --exchange binance
    python run.py keycheck --exchange okx
    python run.py keycheck --from-json snapshot.json
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

SEVERITY_ORDER = {"blocker": 0, "critical": 1, "high": 2, "medium": 3, "info": 4}
SEVERITY_LABEL = {
    "blocker": "BLOCKED",
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "info": "OK",
}


@dataclass(frozen=True)
class Snapshot:
    """Permission flags normalised across exchanges. No secrets live here."""

    exchange: str
    trade: bool = False
    withdrawals: bool = False
    internal_transfer: bool = False
    universal_transfer: bool = False
    futures: bool = False
    spot: bool = False
    ip_restricted: bool | None = None
    expires_in_days: float | None = None
    expiry_known: bool = True
    notes: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    title: str
    detail: str
    fix: str


@dataclass
class Report:
    snapshot: Snapshot
    findings: list[Finding]

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in ("blocker", "critical", "high")]

    @property
    def verdict(self) -> str:
        if any(f.severity == "blocker" for f in self.findings):
            return "blocked"
        if any(f.severity in ("critical", "high") for f in self.findings):
            return "unsafe"
        if any(f.severity == "medium" for f in self.findings):
            return "warnings"
        return "pass"

    @property
    def exit_code(self) -> int:
        return 1 if self.blocking else 0

    def codes(self) -> list[str]:
        return [f.code for f in self.findings]


def _days_left(expiry_ms: int | float | None, now_ms: int) -> float | None:
    if not expiry_ms:
        return None
    return max((float(expiry_ms) - now_ms) / 86_400_000.0, 0.0)


def from_binance(payload: dict, now_ms: int | None = None) -> Snapshot:
    now = int(time.time() * 1000) if now_ms is None else now_ms
    futures = bool(payload.get("enableFutures"))
    spot = bool(payload.get("enableSpotAndMarginTrading") or payload.get("enableMargin"))
    expiry = payload.get("tradingAuthorityExpirationTime")
    return Snapshot(
        exchange="binance",
        trade=bool(futures or spot),
        withdrawals=bool(payload.get("enableWithdrawals")),
        internal_transfer=bool(payload.get("enableInternalTransfer")),
        universal_transfer=bool(payload.get("permitsUniversalTransfer")),
        futures=futures,
        spot=spot,
        ip_restricted=bool(payload["ipRestrict"]) if "ipRestrict" in payload else None,
        expires_in_days=_days_left(expiry, now),
        raw=dict(payload),
    )


def from_okx(payload: dict, now_ms: int | None = None) -> Snapshot:
    data = (payload.get("data") or [{}])[0]
    perms = {item.strip().lower() for item in str(data.get("perm", "")).split(",") if item.strip()}
    trade = "trade" in perms
    return Snapshot(
        exchange="okx",
        trade=trade,
        withdrawals="withdraw" in perms,
        internal_transfer="transfer" in perms,
        universal_transfer=False,
        # OKX does not expose contract-only permissions separately: a key with
        # "trade" can trade whatever the account level allows.
        futures=trade,
        spot=False,
        ip_restricted=None,
        expires_in_days=None,
        expiry_known=False,
        notes=(
            "OKX 不通过 API 暴露 IP 白名单与到期时间，这两项需在网页端人工确认",
            "OKX 的 perm 字段不区分现货/合约，futures 标记按 trade 推断",
        ),
        raw=dict(payload),
    )


def from_manual(payload: dict) -> Snapshot:
    allowed = {
        "exchange", "trade", "withdrawals", "internal_transfer", "universal_transfer",
        "futures", "spot", "ip_restricted", "expires_in_days",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown snapshot fields: {sorted(unknown)}")
    data = {k: v for k, v in payload.items() if k in allowed}
    data.setdefault("exchange", "manual")
    data["exchange"] = str(data["exchange"])
    return Snapshot(
        **data,
        expiry_known="expires_in_days" in data,
        notes=("手工输入的快照：数值未经交易所校验",),
        raw=dict(payload),
    )


def evaluate(snapshot: Snapshot, profile: str = "perp") -> Report:
    findings: list[Finding] = []

    def add(severity: str, code: str, title: str, detail: str, fix: str) -> None:
        findings.append(Finding(severity, code, title, detail, fix))

    if snapshot.withdrawals:
        add(
            "critical", "WITHDRAWALS", "提现权限已开启",
            "这把 key 可以直接把资产提出交易所。风控层挡不住提现，交易所的 IP 限制也只在"
            "绑定后才有效——一旦 key 泄漏，资金上限就是账户全部余额。",
            "在交易所后台关闭提现权限，重新生成一把只带交易权限的 key。",
        )
    if snapshot.universal_transfer:
        add(
            "critical", "UNIVERSAL_TRANSFER", "万能划转已开启",
            "可以在现货、合约、资金账户之间任意搬运资产，等价于对全部余额的支配权。",
            "关闭万能划转，只保留交易所需的权限。",
        )
    elif snapshot.internal_transfer:
        add(
            "high", "INTERNAL_TRANSFER", "内部划转已开启",
            "可以在自己名下的账户/钱包之间转移资产。危害小于提现，但会把损失面从"
            "单一钱包扩大到全部余额。",
            "若策略不需要跨钱包调仓，关闭内部划转。",
        )

    if not snapshot.trade:
        add(
            "blocker", "NO_TRADE", "这把 key 不能下单",
            "没有任何交易权限，策略接上去会全部被交易所拒绝。",
            "按最小权限重新签发：只勾选交易（合约）+ 读取，不提现、不划转。",
        )
    elif profile == "perp":
        if not snapshot.futures:
            add(
                "blocker", "NO_FUTURES", "没有合约权限",
                "只开了现货权限。永续策略的所有下单都会被拒。",
                "勾选合约（USDT-M）交易权限。",
            )
        elif snapshot.spot:
            add(
                "medium", "OVERPERMITTED_SPOT", "同时开了现货权限",
                "策略只用永续，却额外给了现货权限：同样的泄漏风险，更大的攻击面。",
                "如果不需要现货，取消勾选。",
            )

    if snapshot.ip_restricted is False:
        add(
            "high", "NO_IP_ALLOWLIST", "未绑定 IP 白名单",
            "这把 key 从世界任何地方都能用。key 泄漏后，攻击者不需要接触你的机器。",
            "绑定服务器出口 IP；如果 IP 会变，至少绑定固定网段。",
        )
    elif snapshot.ip_restricted is None:
        add(
            "medium", "IP_UNKNOWN", "无法确认 IP 白名单",
            "该交易所的权限接口没有返回 IP 限制状态，体检结论在这一项上是空的。",
            "在交易所网页端查看该 key 是否绑定了 IP 白名单。",
        )

    if not snapshot.expiry_known:
        add(
            "medium", "EXPIRY_UNKNOWN", "无法确认 key 的到期时间",
            "该交易所的权限接口没有返回到期时间，体检结论在这一项上是空的。",
            "在交易所网页端查看该 key 是否设置了有效期。",
        )
    elif snapshot.expires_in_days is None:
        add(
            "high", "NO_EXPIRY", "key 永不过期",
            "泄漏之后没有自动止损点，只能靠你发现。",
            "设置到期时间（例如 30–90 天），到期前轮换。",
        )
    elif snapshot.expires_in_days > 180:
        add(
            "medium", "LONG_EXPIRY", f"key 还能用 {snapshot.expires_in_days:.0f} 天",
            "到期时间太远，泄漏窗口很长。",
            "把有效期压到 90 天以内，并建立轮换日历。",
        )

    if not findings:
        add(
            "info", "CLEAN", "权限配置符合最小权限",
            "只读 + 交易 + 合约，不含提现与划转，且绑定了 IP 白名单与到期时间。",
            "无需改动。定期复核即可。",
        )

    findings.sort(key=lambda f: SEVERITY_ORDER[f.severity])
    return Report(snapshot=snapshot, findings=findings)


def blast_radius(snapshot: Snapshot) -> list[str]:
    """One line per capability, phrased as what a leaked key could do."""
    lines: list[str] = []
    if snapshot.withdrawals:
        lines.append("提现 → 账户资产可被直接转出交易所")
    if snapshot.universal_transfer:
        lines.append("万能划转 → 全部钱包余额可被搬空")
    elif snapshot.internal_transfer:
        lines.append("内部划转 → 资金可在你的账户间挪动")
    if snapshot.trade:
        lines.append("下单 → 可反向开仓，损失上限 = 账户全部权益")
    lines.append("读取 → 余额、持仓、成交记录全部可见")
    if snapshot.ip_restricted:
        lines.append("IP 白名单 → 即使泄漏，也只能从你的 IP 发起")
    if snapshot.expires_in_days is not None:
        lines.append(f"到期 → 还剩 {snapshot.expires_in_days:.0f} 天自动失效")
    return lines


def render_text(report: Report) -> str:
    snapshot = report.snapshot
    head = [
        f"API key audit — {snapshot.exchange} (profile: perp)",
        "-" * 62,
    ]
    body: list[str] = []
    for finding in report.findings:
        body.append(f"[{SEVERITY_LABEL[finding.severity]:8s}] {finding.code:18s} {finding.title}")
        body.append(f"           why: {finding.detail}")
        body.append(f"           fix: {finding.fix}")
        body.append("")
    for note in snapshot.notes:
        body.append(f"note: {note}")
    if snapshot.notes:
        body.append("")
    body.append("Blast radius if this key leaks:")
    body.extend(f"  • {line}" for line in blast_radius(snapshot))
    body.append("")
    counts = {}
    for finding in report.findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    summary = ", ".join(f"{counts[s]} {s}" for s in SEVERITY_ORDER if s in counts)
    body.append(f"Verdict: {report.verdict.upper()} ({summary})")
    return "\n".join(head + body)


def render_json(report: Report) -> str:
    snapshot = report.snapshot
    payload = {
        "exchange": snapshot.exchange,
        "verdict": report.verdict,
        "exit_code": report.exit_code,
        "permissions": {
            "trade": snapshot.trade,
            "withdrawals": snapshot.withdrawals,
            "internal_transfer": snapshot.internal_transfer,
            "universal_transfer": snapshot.universal_transfer,
            "futures": snapshot.futures,
            "spot": snapshot.spot,
            "ip_restricted": snapshot.ip_restricted,
            "expires_in_days": snapshot.expires_in_days,
            "expiry_known": snapshot.expiry_known,
        },
        "findings": [f.__dict__ for f in report.findings],
        "blast_radius": blast_radius(snapshot),
        "notes": list(snapshot.notes),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def fetch_binance(api_key: str, api_secret: str, base: str = "https://api.binance.com") -> Snapshot:
    now = int(time.time() * 1000)
    query = f"timestamp={now}&recvWindow=5000"
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{base}/sapi/v1/account/apiRestrictions?{query}&signature={signature}"
    request = urllib.request.Request(url, headers={"X-MBX-APIKEY": api_key})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    return from_binance(payload, now_ms=now)


def fetch_okx(
    api_key: str,
    api_secret: str,
    passphrase: str,
    base: str = "https://www.okx.com",
) -> Snapshot:
    path = "/api/v5/account/config"
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    stamp = f"{stamp}.{int(time.time() * 1000) % 1000:03d}Z"
    prehash = f"{stamp}GET{path}"
    signature = base64.b64encode(
        hmac.new(api_secret.encode(), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    request = urllib.request.Request(
        base + path,
        headers={
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": stamp,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX rejected the request: {payload.get('code')} {payload.get('msg')}")
    return from_okx(payload)


def snapshot_from_env(exchange: str) -> Snapshot:
    if exchange == "binance":
        key, secret = os.environ.get("BINANCE_API_KEY"), os.environ.get("BINANCE_API_SECRET")
        if not key or not secret:
            raise SystemExit("set BINANCE_API_KEY and BINANCE_API_SECRET (read-only key is enough)")
        return fetch_binance(key, secret)
    if exchange == "okx":
        key = os.environ.get("OKX_API_KEY")
        secret = os.environ.get("OKX_API_SECRET")
        passphrase = os.environ.get("OKX_API_PASSPHRASE")
        if not key or not secret or not passphrase:
            raise SystemExit("set OKX_API_KEY, OKX_API_SECRET and OKX_API_PASSPHRASE")
        return fetch_okx(key, secret, passphrase)
    raise SystemExit(f"unknown exchange {exchange!r} (use binance or okx)")
