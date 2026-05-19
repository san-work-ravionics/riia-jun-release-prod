"""Unit tests for SqlRepository via PositionsRepository.

All tests use the ``db_session`` fixture from conftest.py which provides an
isolated in-memory SQLite database per test function.  No CSV files are
created or read by these tests.
"""

from __future__ import annotations

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Test fixture helpers
# ---------------------------------------------------------------------------

def make_position(n: int):
    """Return a minimal but realistic Position record."""
    from rita.schemas.positions import Position

    return Position(
        position_id=f"pos-{n}",
        instrument=f"NIFTY{n}CE",
        underlying="NIFTY",
        quantity=75,
        avg_price=100.0,
        last_traded_price=105.0,
        pnl=375.0,
        recorded_at=datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc),
    )


def make_repo(session):
    """Construct a PositionsRepository backed by the given SQLAlchemy session."""
    from rita.repositories.positions import PositionsRepository

    return PositionsRepository(session)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReadAllEmptyTable:
    def test_read_all_empty_table(self, db_session):
        """A freshly created session with no rows returns an empty list."""
        repo = make_repo(db_session)
        assert repo.read_all() == []


class TestWriteAndReadRoundTrip:
    def test_write_and_read_round_trip(self, db_session):
        """write_all then read_all returns the same records."""
        repo = make_repo(db_session)
        records = [make_position(i) for i in range(3)]

        repo.write_all(records)
        result = repo.read_all()

        assert len(result) == 3
        result_ids = {r.position_id for r in result}
        assert result_ids == {"pos-0", "pos-1", "pos-2"}

        # Spot-check fields that survive ORM round-trip
        for original in records:
            match = next(r for r in result if r.position_id == original.position_id)
            assert match.quantity == original.quantity
            assert match.pnl == original.pnl


class TestUpsertInsertsNewRecord:
    def test_upsert_inserts_new_record(self, db_session):
        """Upsert a record not yet in the table; read_all contains it."""
        repo = make_repo(db_session)
        pos = make_position(1)

        repo.upsert(pos)
        result = repo.read_all()

        assert len(result) == 1
        assert result[0].position_id == "pos-1"


class TestUpsertReplacesExisting:
    def test_upsert_replaces_existing(self, db_session):
        """Upsert a record with the same id; old value is replaced."""
        repo = make_repo(db_session)
        original = make_position(1)
        repo.upsert(original)

        updated = make_position(1)
        updated = updated.model_copy(update={"avg_price": 200.0})
        repo.upsert(updated)

        result = repo.read_all()
        assert len(result) == 1
        assert result[0].avg_price == 200.0


class TestDeleteRemovesRecord:
    def test_delete_removes_record(self, db_session):
        """Delete by id; record is gone from read_all."""
        repo = make_repo(db_session)
        for i in range(3):
            repo.upsert(make_position(i))

        removed = repo.delete("pos-1")

        assert removed is True
        ids = {r.position_id for r in repo.read_all()}
        assert "pos-1" not in ids
        assert "pos-0" in ids
        assert "pos-2" in ids


class TestDeleteReturnsFalseWhenNotFound:
    def test_delete_returns_false_when_not_found(self, db_session):
        """Delete a non-existent id returns False."""
        repo = make_repo(db_session)
        repo.upsert(make_position(1))

        result = repo.delete("pos-999")

        assert result is False
        assert len(repo.read_all()) == 1


class TestFindByIdReturnsCorrect:
    def test_find_by_id_returns_correct(self, db_session):
        """find_by_id returns the right record."""
        repo = make_repo(db_session)
        for i in range(5):
            repo.upsert(make_position(i))

        found = repo.find_by_id("pos-3")

        assert found is not None
        assert found.position_id == "pos-3"
        assert found.instrument == "NIFTY3CE"


class TestFindByIdReturnsNoneWhenMissing:
    def test_find_by_id_returns_none_when_missing(self, db_session):
        """find_by_id returns None for an unknown id."""
        repo = make_repo(db_session)
        repo.upsert(make_position(1))

        result = repo.find_by_id("pos-999")

        assert result is None


class TestWriteAllThenReadAll:
    def test_write_all_then_read_all(self, db_session):
        """write_all N records then read_all returns exactly N records."""
        repo = make_repo(db_session)
        n = 5
        records = [make_position(i) for i in range(n)]

        repo.write_all(records)
        result = repo.read_all()

        assert len(result) == n
        result_ids = {r.position_id for r in result}
        expected_ids = {f"pos-{i}" for i in range(n)}
        assert result_ids == expected_ids


class TestWriteAllEmptyList:
    def test_write_all_empty_list(self, db_session):
        """write_all([]) then read_all() returns an empty list."""
        repo = make_repo(db_session)

        # Pre-populate so write_all([]) has something to clear
        repo.upsert(make_position(1))
        assert len(repo.read_all()) == 1

        repo.write_all([])
        assert repo.read_all() == []


class TestUpsertManyRecords:
    def test_upsert_many_records(self, db_session):
        """Upsert 10 records sequentially; read_all returns exactly 10."""
        repo = make_repo(db_session)
        n = 10

        for i in range(n):
            repo.upsert(make_position(i))

        result = repo.read_all()
        ids = {r.position_id for r in result}

        assert len(result) == n, f"Expected {n} records, got {len(result)}"
        assert ids == {f"pos-{i}" for i in range(n)}
