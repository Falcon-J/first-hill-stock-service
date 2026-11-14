"""Busy journal-mode initialization must recover without weakening allocation locks."""
from datetime import datetime, timezone
import sqlite3
from types import SimpleNamespace

import pytest

from services.stock.inventory import Inventory


def test_stock_startup_retries_transient_wal_busy(tmp_path, monkeypatch):
    connect = sqlite3.connect
    calls = []

    class BusyJournal:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, *args):
            if statement == 'PRAGMA journal_mode=WAL':
                calls.append(statement)
                if len(calls) < 3:
                    error = sqlite3.OperationalError('database is locked')
                    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                    raise error
            return self.connection.execute(statement, *args)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: BusyJournal(connect(*a, **kw)))
    inventory = Inventory({'stores': {}, 'recipes': {}},
        lambda: datetime.now(timezone.utc), tmp_path / 'startup.sqlite')
    assert len(calls) == 3
    assert inventory.connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert inventory.data['reservations'] == {}


def test_stock_startup_does_not_retry_io_errors(tmp_path, monkeypatch):
    connect = sqlite3.connect
    calls, closed = [], []

    class BadJournal:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, *args):
            calls.append(statement)
            error = sqlite3.OperationalError('disk I/O error')
            error.sqlite_errorcode = sqlite3.SQLITE_IOERR
            raise error

        def close(self):
            closed.append(True)
            self.connection.close()

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: BadJournal(connect(*a, **kw)))
    with pytest.raises(sqlite3.OperationalError, match='disk I/O'):
        Inventory({'stores': {}, 'recipes': {}}, lambda: datetime.now(timezone.utc), tmp_path / 'bad.sqlite')
    assert len(calls) == 1
    assert closed == [True]


def test_wal_busy_retry_stops_at_deadline(monkeypatch):
    import services.stock.inventory as module
    ticks, calls, sleeps = iter([0, 2]), [], []
    monkeypatch.setattr(module, 'time', SimpleNamespace(
        monotonic=lambda: next(ticks), sleep=lambda delay: sleeps.append(delay)))

    class AlwaysBusy:
        def execute(self, statement):
            calls.append(statement)
            error = sqlite3.OperationalError('database is locked')
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error

    with pytest.raises(sqlite3.OperationalError, match='locked'):
        module.enable_wal(AlwaysBusy())
    assert len(calls) == 1
    assert sleeps == []
