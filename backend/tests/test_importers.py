"""Parsing MT5 HTML reports and generic CSV exports."""

from __future__ import annotations

import io
import pathlib

import pytest

from app.services.importers import parse_mt5_html_report, parse_trades_csv

MT5_REPORT = """
<html><body><table>
<tr><td colspan="13" align="center"><b>Trade History Report</b></td></tr>
<tr><td colspan="13">Name: Kasper</td></tr>
<tr><td colspan="13">Account: 5000123 (Kasper, USD, TestBroker-Live, hedge)</td></tr>
<tr><th colspan="13">Positions</th></tr>
<tr><th>Time</th><th>Position</th><th>Symbol</th><th>Type</th><th>Volume</th>
    <th>Price</th><th>S / L</th><th>T / P</th><th>Time</th><th>Price</th>
    <th>Commission</th><th>Swap</th><th>Profit</th></tr>
<tr><td>2026.06.01 10:00:00</td><td>5001</td><td>eurusd</td><td>buy</td><td>1.00</td>
    <td>1.10000</td><td>1.09800</td><td>1.10600</td><td>2026.06.01 12:00:00</td>
    <td>1.10400</td><td>-7.00</td><td>0.00</td><td>400.00</td></tr>
<tr><td>2026.06.02 08:30:00</td><td>5002</td><td>XAUUSD</td><td>sell</td><td>0.50</td>
    <td>2 350.00</td><td>2 360.00</td><td></td><td>2026.06.02 09:15:00</td>
    <td>2 358.00</td><td>-3.50</td><td>-1.20</td><td>-400.00</td></tr>
<tr><th colspan="13">Orders</th></tr>
<tr><td>2026.06.03 10:00:00</td><td>7001</td><td>EURUSD</td><td>buy limit</td><td>1.00</td>
    <td>1.09000</td><td></td><td></td><td>2026.06.03 10:00:00</td><td>1.09000</td>
    <td></td><td></td><td>canceled</td></tr>
</table></body></html>
"""


class TestMT5HtmlReport:
    def test_account_header_is_recognised(self):
        account = parse_mt5_html_report(MT5_REPORT)["account"]
        assert account["login"] == "5000123"
        assert account["name"] == "Kasper"
        assert account["currency"] == "USD"
        assert account["server"] == "TestBroker-Live"

    def test_only_position_rows_are_taken(self):
        positions = parse_mt5_html_report(MT5_REPORT)["positions"]
        assert len(positions) == 2
        assert {p["position_id"] for p in positions} == {5001, 5002}

    def test_long_position_fields(self):
        first = parse_mt5_html_report(MT5_REPORT)["positions"][0]
        assert first["symbol"] == "EURUSD"
        assert first["direction"] == "long"
        assert first["volume"] == pytest.approx(1.0)
        assert first["entry_price"] == pytest.approx(1.10000)
        assert first["exit_price"] == pytest.approx(1.10400)
        assert first["initial_stop"] == pytest.approx(1.09800)
        assert first["initial_target"] == pytest.approx(1.10600)
        assert first["gross_profit"] == pytest.approx(400.0)
        assert first["commission"] == pytest.approx(-7.0)
        assert first["opened_at"].isoformat().startswith("2026-06-01T10:00")

    def test_short_position_and_thousands_separators(self):
        second = parse_mt5_html_report(MT5_REPORT)["positions"][1]
        assert second["direction"] == "short"
        assert second["entry_price"] == pytest.approx(2350.0)
        assert second["initial_target"] is None
        assert second["gross_profit"] == pytest.approx(-400.0)
        assert second["swap"] == pytest.approx(-1.2)

    def test_empty_document(self):
        assert parse_mt5_html_report("<html></html>")["positions"] == []


class TestCsvImport:
    def test_standard_headers(self):
        csv_text = (
            "Symbol,Type,Volume,Open Time,Open Price,Close Time,Close Price,S/L,T/P,Profit,Commission\n"
            "EURUSD,Buy,1.0,2026-06-01 10:00:00,1.1000,2026-06-01 12:00:00,1.1040,1.0980,1.1060,400,-7\n"
            "XAUUSD,Sell,0.5,2026-06-02 08:30:00,2350,2026-06-02 09:15:00,2358,2360,,-400,-3.5\n"
        )
        rows = parse_trades_csv(csv_text)
        assert len(rows) == 2
        assert rows[0]["symbol"] == "EURUSD"
        assert rows[0]["direction"] == "long"
        assert rows[1]["direction"] == "short"
        assert rows[0]["gross_profit"] == pytest.approx(400.0)

    def test_semicolon_delimiter_and_alternative_names(self):
        csv_text = (
            "instrument;side;lots;opentime;entry;exittime;exit;pnl\n"
            "GBPUSD;long;2.0;2026.06.05 09:00:00;1.2700;2026.06.05 11:00:00;1.2750;1000\n"
        )
        rows = parse_trades_csv(csv_text)
        assert len(rows) == 1
        assert rows[0]["symbol"] == "GBPUSD"
        assert rows[0]["volume"] == pytest.approx(2.0)
        assert rows[0]["gross_profit"] == pytest.approx(1000.0)

    def test_tags_and_notes_are_carried_over(self):
        csv_text = (
            "symbol,type,open time,price,profit,tags,notes\n"
            "US30,buy,2026-06-06 15:30:00,39000,250,FOMO trade|Late entry,Chased the move\n"
        )
        row = parse_trades_csv(csv_text)[0]
        assert row["tags"] == ["FOMO trade", "Late entry"]
        assert row["notes"] == "Chased the move"

    def test_rows_without_a_date_are_skipped(self):
        csv_text = "symbol,open time,price\nEURUSD,,1.1\nEURUSD,2026-06-01 10:00:00,1.1\n"
        assert len(parse_trades_csv(csv_text)) == 1

    def test_missing_symbol_column_is_an_error(self):
        with pytest.raises(ValueError):
            parse_trades_csv("a,b,c\n1,2,3\n")

    def test_empty_file(self):
        assert parse_trades_csv("") == []


class TestImportEndpoint:
    def test_upload_html_report(self, auth_client):
        response = auth_client.post(
            "/api/import/file",
            files={"file": ("report.html", io.BytesIO(MT5_REPORT.encode()), "text/html")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["kind"] == "mt5_html"
        assert body["created"] == 2

        trades = auth_client.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()["items"]
        assert len(trades) == 2
        eurusd = next(t for t in trades if t["symbol"] == "EURUSD")
        # value per unit is inferred from the realised result, so R still works
        assert eurusd["risk_amount"] == pytest.approx(200.0, rel=1e-3)
        assert eurusd["realized_r"] == pytest.approx(1.965, rel=1e-3)

    def test_dry_run_changes_nothing(self, auth_client):
        response = auth_client.post(
            "/api/import/file",
            files={"file": ("report.html", io.BytesIO(MT5_REPORT.encode()), "text/html")},
            data={"dry_run": "true"},
        )
        body = response.json()
        assert body["dry_run"] is True
        assert body["found"] == 2
        assert auth_client.get("/api/trades", params={"period": "all"}).json()["total"] == 0

    def test_reimport_updates_rather_than_duplicates(self, auth_client):
        files = {"file": ("report.html", io.BytesIO(MT5_REPORT.encode()), "text/html")}
        auth_client.post("/api/import/file", files=files)
        again = auth_client.post(
            "/api/import/file",
            files={"file": ("report.html", io.BytesIO(MT5_REPORT.encode()), "text/html")},
        ).json()
        assert again["created"] == 0
        assert again["updated"] == 2

    def test_unparseable_file_is_rejected(self, auth_client):
        response = auth_client.post(
            "/api/import/file",
            files={"file": ("junk.txt", io.BytesIO(b"nothing useful here"), "text/plain")},
        )
        assert response.status_code == 400

    def test_csv_upload(self, auth_client):
        csv_text = (
            "Symbol,Type,Volume,Open Time,Open Price,Close Time,Close Price,S/L,Profit\n"
            "EURUSD,Buy,1.0,2026-06-01 10:00:00,1.1000,2026-06-01 12:00:00,1.1040,1.0980,400\n"
        )
        response = auth_client.post(
            "/api/import/file",
            files={"file": ("trades.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        )
        assert response.status_code == 200
        assert response.json()["created"] == 1


class TestRealMetaTraderReports:
    """Both exports of one history, parsed from the files MetaTrader wrote.

    The HTML export carries an unnamed comment cell after Type that its own
    header does not mention, so its rows are one wider than the spreadsheet's.
    Fixed column indices read one correctly and shifted every field of the
    other -- volume into price, price into the stop, the close price into
    commission -- and the import looked like it had worked.
    """

    FIXTURES = pathlib.Path(__file__).parent / "fixtures"

    def _html(self):
        from app.services.importers import parse_mt5_html_report

        return parse_mt5_html_report(
            (self.FIXTURES / "mt5_report.html").read_bytes().decode("utf-16")
        )

    def _xlsx(self):
        from app.services.importers import parse_mt5_xlsx_report

        return parse_mt5_xlsx_report((self.FIXTURES / "mt5_report.xlsx").read_bytes())

    @pytest.mark.parametrize("which", ["html", "xlsx"])
    def test_the_account_block_is_read_correctly(self, which):
        account = (self._html() if which == "html" else self._xlsx())["account"]
        assert account["login"] == "25702871"
        assert account["currency"] == "USD"
        assert account["server"] == "VantageMarkets-Demo"
        # Previously the holder's name was taken from inside the parentheses,
        # which filed the import under an account called "USD".
        assert account["name"] == "KASPER SKYTTE ANDERSEN"
        assert account["broker"] == "Vantage Markets (Pty) Ltd"

    @pytest.mark.parametrize("which", ["html", "xlsx"])
    def test_the_first_trade_maps_to_the_right_columns(self, which):
        trade = (self._html() if which == "html" else self._xlsx())["positions"][0]
        assert trade["position_id"] == 1530955433
        assert trade["symbol"] == "XAUUSD+"
        assert trade["direction"] == "long"
        assert trade["volume"] == 0.05
        assert trade["entry_price"] == 4064.29
        assert trade["initial_stop"] == 4054.35
        assert trade["initial_target"] == 4079.35
        assert trade["exit_price"] == 4079.35
        assert trade["commission"] == -0.30
        assert trade["swap"] == 0.0
        assert trade["gross_profit"] == 75.30
        assert trade["closed_at"] is not None

    def test_both_exports_of_the_same_history_agree(self):
        html, xlsx = self._html()["positions"], self._xlsx()["positions"]
        assert len(html) == len(xlsx) > 0
        for a, b in zip(html, xlsx, strict=True):
            assert a == b

    def test_an_unnamed_comment_column_does_not_shift_the_fields(self):
        """The HTML rows are 14 wide against a 13-column header."""
        from app.services.importers import position_from_row

        without = [
            "2026.07.02 15:15:00", "1530955433", "XAUUSD+", "buy",
            "0.05", "4064.29", "4054.35", "4079.35",
            "2026.07.02 15:30:04", "4079.35", "-0.30", "0.00", "75.30",
        ]
        with_comment = without[:4] + ["MB new"] + without[4:]
        assert position_from_row(without) == position_from_row(with_comment)

    def test_a_row_that_is_not_a_trade_is_ignored(self):
        from app.services.importers import position_from_row

        assert position_from_row(["Time", "Position", "Symbol", "Type"] + [""] * 10) is None
        assert position_from_row([]) is None
