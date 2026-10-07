import asyncio
import logging
import re
import time

from mmrbot import perf


def test_phases_accumulate_and_are_formatted_in_fixed_order():
    trace = perf.begin()
    with perf.phase("build"):
        time.sleep(0.02)
    with perf.phase("refresh"):
        time.sleep(0.03)
    with perf.phase("build"):
        time.sleep(0.02)
    line = perf.format_line("/stats", -100123, 0.5, trace.phases)
    assert re.fullmatch(
        r"perf cmd=/stats chat=-100123 total=0\.50s refresh=0\.0\ds build=0\.0\ds send=0\.\d\ds", line), line
    assert trace.phases["build"] >= 0.04 and trace.phases["refresh"] >= 0.03


def test_send_is_the_remainder_never_negative():
    line = perf.format_line("/x", 1, 0.10, {"refresh": 0.08, "build": 0.05})
    assert "send=0.00s" in line
    assert "send=0.40s" in perf.format_line("/x", 1, 0.5, {"refresh": 0.05, "build": 0.05})


def test_missing_phases_are_skipped():
    assert perf.format_line("cb:m:week", 7, 1.0, {}) == "perf cmd=cb:m:week chat=7 total=1.00s send=1.00s"


def test_phase_without_active_trace_is_noop():
    perf._current.set(None)
    with perf.phase("build"):
        pass  # не падает и ничего не пишет


def test_phases_are_recorded_from_worker_threads():
    async def go():
        trace = perf.begin()

        def work():
            with perf.phase("build"):
                time.sleep(0.02)

        await asyncio.to_thread(work)  # service гоняет сборку в потоке — контекст должен доехать
        return trace

    assert asyncio.run(go()).phases["build"] >= 0.02


def test_finish_logs_one_info_line(caplog):
    async def go():
        trace = perf.begin()
        with perf.phase("render"):
            await asyncio.sleep(0.01)
        return perf.finish(trace, "/stats", 42)

    with caplog.at_level(logging.INFO, logger="mmrbot.perf"):
        line = asyncio.run(go())
    records = [r for r in caplog.records if r.name == "mmrbot.perf"]
    assert len(records) == 1 and records[0].levelno == logging.INFO
    assert records[0].getMessage() == line and line.startswith("perf cmd=/stats chat=42 total=")
    assert perf._current.get() is None  # трассировка закрыта


def test_label_for_event_kinds():
    class Msg:
        text = "/stats@mybot сегодня"

    class Plain:
        text = "привет всем"

    class Cb:
        data = "m:week"

    assert perf.label(Msg()) == "/stats"
    assert perf.label(Plain()) == "text"
    assert perf.label(Cb()) == "cb:m:week"
