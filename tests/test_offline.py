import socket

import pytest

from ontology_gate import demo


def test_the_guard_blocks_outbound_connections():
    with pytest.raises(OSError, match="blocked"):
        socket.create_connection(("192.0.2.1", 443), timeout=1)
    with pytest.raises(OSError, match="blocked"):
        socket.getaddrinfo("example.org", 443)


def test_demo_runs_offline(capsys):
    assert demo.main(["--defect"]) == 0
    out = capsys.readouterr().out
    assert "correct: 2 refunds paid, 1 escalated, no order paid twice" in out
    assert "defect: duplicate refund for o1001 paid 3 times before escalation" in out


def test_demo_output_is_plain_text(capsys):
    demo.main(["--defect"])
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    assert "—" not in out and "–" not in out
    assert all(line == line.rstrip() for line in out.splitlines())


def test_live_mode_needs_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        demo.main(["--live"])
