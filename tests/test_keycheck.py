"""keycheck: the verdict must follow the permission flags, not the wording.

Run with: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qe_study import keycheck  # noqa: E402
from qe_study.cli import main  # noqa: E402

DAY_MS = 86_400_000
NOW = 1_700_000_000_000


def binance_payload(**overrides) -> dict:
    payload = {
        "ipRestrict": True,
        "enableReading": True,
        "enableWithdrawals": False,
        "enableInternalTransfer": False,
        "permitsUniversalTransfer": False,
        "enableFutures": True,
        "enableSpotAndMarginTrading": False,
        "enableMargin": False,
        "tradingAuthorityExpirationTime": NOW + 30 * DAY_MS,
    }
    payload.update(overrides)
    return payload


def okx_payload(perm: str) -> dict:
    return {"code": "0", "data": [{"perm": perm, "acctLv": "2", "posMode": "net_mode"}]}


class BinanceParsingTest(unittest.TestCase):
    def test_clean_perp_key_passes(self) -> None:
        report = keycheck.evaluate(keycheck.from_binance(binance_payload(), now_ms=NOW))
        self.assertEqual(report.verdict, "pass")
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.codes(), ["CLEAN"])

    def test_withdrawals_is_critical(self) -> None:
        report = keycheck.evaluate(
            keycheck.from_binance(binance_payload(enableWithdrawals=True), now_ms=NOW)
        )
        self.assertIn("WITHDRAWALS", report.codes())
        self.assertEqual(report.verdict, "unsafe")
        self.assertEqual(report.exit_code, 1)

    def test_universal_transfer_is_critical(self) -> None:
        report = keycheck.evaluate(
            keycheck.from_binance(binance_payload(permitsUniversalTransfer=True), now_ms=NOW)
        )
        self.assertIn("UNIVERSAL_TRANSFER", report.codes())
        self.assertEqual(report.verdict, "unsafe")

    def test_internal_transfer_is_high_not_critical(self) -> None:
        report = keycheck.evaluate(
            keycheck.from_binance(binance_payload(enableInternalTransfer=True), now_ms=NOW)
        )
        finding = next(f for f in report.findings if f.code == "INTERNAL_TRANSFER")
        self.assertEqual(finding.severity, "high")

    def test_missing_ip_allowlist_is_high(self) -> None:
        report = keycheck.evaluate(
            keycheck.from_binance(binance_payload(ipRestrict=False), now_ms=NOW)
        )
        self.assertIn("NO_IP_ALLOWLIST", report.codes())
        self.assertEqual(report.exit_code, 1)

    def test_no_trade_permission_is_a_blocker(self) -> None:
        report = keycheck.evaluate(
            keycheck.from_binance(
                binance_payload(enableFutures=False, enableSpotAndMarginTrading=False), now_ms=NOW
            )
        )
        self.assertIn("NO_TRADE", report.codes())
        self.assertEqual(report.verdict, "blocked")

    def test_spot_only_key_cannot_run_a_perp_strategy(self) -> None:
        report = keycheck.evaluate(
            keycheck.from_binance(
                binance_payload(enableFutures=False, enableSpotAndMarginTrading=True), now_ms=NOW
            )
        )
        self.assertIn("NO_FUTURES", report.codes())
        self.assertEqual(report.verdict, "blocked")

    def test_expiry_is_read_from_the_authority_timestamp(self) -> None:
        snapshot = keycheck.from_binance(
            binance_payload(tradingAuthorityExpirationTime=NOW + 45 * DAY_MS), now_ms=NOW
        )
        self.assertAlmostEqual(snapshot.expires_in_days or 0, 45.0, places=3)

    def test_zero_expiry_means_never(self) -> None:
        report = keycheck.evaluate(
            keycheck.from_binance(binance_payload(tradingAuthorityExpirationTime=0), now_ms=NOW)
        )
        self.assertIn("NO_EXPIRY", report.codes())


class OkxParsingTest(unittest.TestCase):
    def test_read_only_trade_key_has_no_withdrawal_finding(self) -> None:
        report = keycheck.evaluate(keycheck.from_okx(okx_payload("read_only,trade")))
        self.assertNotIn("WITHDRAWALS", report.codes())
        self.assertIn("IP_UNKNOWN", report.codes())
        self.assertEqual(report.verdict, "warnings")

    def test_withdraw_permission_is_caught(self) -> None:
        report = keycheck.evaluate(keycheck.from_okx(okx_payload("trade,withdraw")))
        self.assertIn("WITHDRAWALS", report.codes())
        self.assertEqual(report.exit_code, 1)

    def test_transfer_permission_is_caught(self) -> None:
        report = keycheck.evaluate(keycheck.from_okx(okx_payload("read_only,trade,transfer")))
        self.assertIn("INTERNAL_TRANSFER", report.codes())

    def test_okx_notes_say_what_the_api_cannot_see(self) -> None:
        snapshot = keycheck.from_okx(okx_payload("trade"))
        self.assertTrue(any("IP" in note for note in snapshot.notes))


class ManualSnapshotTest(unittest.TestCase):
    def test_unknown_fields_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            keycheck.from_manual({"exchange": "binance", "withdrawl": True})

    def test_manual_snapshot_is_evaluated_like_a_fetched_one(self) -> None:
        snapshot = keycheck.from_manual(
            {"exchange": "binance", "trade": True, "withdrawals": True, "futures": True}
        )
        report = keycheck.evaluate(snapshot)
        self.assertIn("WITHDRAWALS", report.codes())


class OutputTest(unittest.TestCase):
    def test_json_output_has_verdict_and_no_secret_material(self) -> None:
        report = keycheck.evaluate(keycheck.from_binance(binance_payload(), now_ms=NOW))
        payload = json.loads(keycheck.render_json(report))
        self.assertEqual(payload["verdict"], "pass")
        self.assertNotIn("secret", keycheck.render_json(report).lower())

    def test_blast_radius_states_what_a_leak_would_allow(self) -> None:
        snapshot = keycheck.from_binance(binance_payload(enableWithdrawals=True), now_ms=NOW)
        lines = "\n".join(keycheck.blast_radius(snapshot))
        self.assertIn("转出", lines)
        self.assertIn("反向开仓", lines)

    def test_cli_exits_nonzero_on_an_unsafe_key(self) -> None:
        snapshot = {
            "exchange": "binance",
            "trade": True,
            "futures": True,
            "withdrawals": True,
            "ip_restricted": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                with self.assertRaises(SystemExit) as raised:
                    main(["keycheck", "--from-json", str(path)])
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("WITHDRAWALS", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
