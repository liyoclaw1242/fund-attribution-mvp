"""Tests for data/portfolio_db.py — client CRUD, portfolio CRUD, CSV import, cross-client queries."""

import pytest

from data.cache import get_connection, init_db
from data.portfolio_db import (
    add_client,
    get_client,
    list_clients,
    search_clients,
    add_holding,
    remove_holding,
    get_portfolio,
    get_all_portfolios,
    get_clients_holding,
    import_from_csv,
)


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


class TestClientCRUD:
    def test_add_and_get(self, db):
        client = add_client(db, "王小明", "aggressive")
        assert client.name == "王小明"
        assert client.kyc_risk_level == "aggressive"

        fetched = get_client(db, client.client_id)
        assert fetched is not None
        assert fetched.name == "王小明"

    def test_get_nonexistent(self, db):
        assert get_client(db, "nonexistent") is None

    def test_list_clients(self, db):
        add_client(db, "王小明")
        add_client(db, "李大華")
        clients = list_clients(db)
        assert len(clients) == 2

    def test_search_clients(self, db):
        add_client(db, "王小明")
        add_client(db, "王大華")
        add_client(db, "李小龍")

        results = search_clients(db, "王")
        assert len(results) == 2
        assert all("王" in c.name for c in results)

    def test_search_no_match(self, db):
        add_client(db, "王小明")
        assert len(search_clients(db, "陳")) == 0

    def test_custom_client_id(self, db):
        client = add_client(db, "Test", client_id="custom-id")
        assert client.client_id == "custom-id"


class TestPortfolioCRUD:
    def test_add_and_get_holdings(self, db):
        client = add_client(db, "王小明")
        add_holding(db, client.client_id, "0050", "元大銀行", 1000, 150000)
        add_holding(db, client.client_id, "00878", "國泰世華", 500, 50000)

        portfolio = get_portfolio(db, client.client_id)
        assert len(portfolio) == 2
        assert portfolio[0].fund_code == "0050"
        assert portfolio[0].shares == 1000

    def test_upsert_holding(self, db):
        client = add_client(db, "王小明")
        add_holding(db, client.client_id, "0050", "元大銀行", 1000, 150000)
        add_holding(db, client.client_id, "0050", "元大銀行", 2000, 300000)  # upsert

        portfolio = get_portfolio(db, client.client_id)
        assert len(portfolio) == 1
        assert portfolio[0].shares == 2000

    def test_remove_holding(self, db):
        client = add_client(db, "王小明")
        add_holding(db, client.client_id, "0050", "", 1000, 150000)

        assert remove_holding(db, client.client_id, "0050") is True
        assert len(get_portfolio(db, client.client_id)) == 0

    def test_remove_nonexistent(self, db):
        assert remove_holding(db, "nope", "0050") is False

    def test_get_all_portfolios(self, db):
        c1 = add_client(db, "王小明")
        c2 = add_client(db, "李大華")
        add_holding(db, c1.client_id, "0050", "", 1000, 150000)
        add_holding(db, c2.client_id, "00878", "", 500, 50000)

        all_holdings = get_all_portfolios(db)
        assert len(all_holdings) == 2

    def test_empty_portfolio(self, db):
        client = add_client(db, "王小明")
        assert get_portfolio(db, client.client_id) == []


class TestCrossClientQueries:
    def test_get_clients_holding_fund(self, db):
        c1 = add_client(db, "王小明")
        c2 = add_client(db, "李大華")
        c3 = add_client(db, "陳小龍")

        add_holding(db, c1.client_id, "00878", "元大", 1000, 100000)
        add_holding(db, c2.client_id, "00878", "國泰", 500, 50000)
        add_holding(db, c3.client_id, "0050", "富邦", 200, 30000)

        holders = get_clients_holding(db, "00878")
        assert len(holders) == 2
        names = {h["name"] for h in holders}
        assert "王小明" in names
        assert "李大華" in names

    def test_no_holders(self, db):
        assert get_clients_holding(db, "99999") == []


class TestCSVImport:
    @pytest.fixture
    def csv_file(self, tmp_path):
        path = tmp_path / "import.csv"
        path.write_text(
            "client_name,fund_code,bank,shares,cost_basis\n"
            "王小明,0050,元大銀行,1000,150000\n"
            "王小明,00878,國泰世華,500,50000\n"
            "李大華,0050,富邦銀行,800,120000\n"
        )
        return path

    def test_import_creates_clients_and_holdings(self, db, csv_file):
        stats = import_from_csv(db, csv_file)
        assert stats["rows_processed"] == 3
        assert stats["clients_created"] == 2
        assert stats["holdings_upserted"] == 3

        clients = list_clients(db)
        assert len(clients) == 2

        # Check Wang's portfolio
        wang = search_clients(db, "王小明")[0]
        portfolio = get_portfolio(db, wang.client_id)
        assert len(portfolio) == 2

    def test_import_idempotent(self, db, csv_file):
        import_from_csv(db, csv_file)
        stats = import_from_csv(db, csv_file)
        # Second import: 0 new clients (already exist), 3 upserts
        assert stats["clients_created"] == 0
        assert stats["holdings_upserted"] == 3
        assert len(list_clients(db)) == 2

    def test_import_missing_file(self, db):
        with pytest.raises(FileNotFoundError):
            import_from_csv(db, "/nonexistent/file.csv")


class TestScalePerformance:
    def test_50_clients_10_funds(self, db):
        """Verify 50+ clients × 10+ funds works without issues."""
        for i in range(50):
            client = add_client(db, f"Client_{i:03d}")
            for j in range(10):
                add_holding(db, client.client_id, f"fund_{j:03d}", "bank", 100 * (j + 1), 1000 * (j + 1))

        assert len(list_clients(db)) == 50
        all_h = get_all_portfolios(db)
        assert len(all_h) == 500

        holders = get_clients_holding(db, "fund_000")
        assert len(holders) == 50
