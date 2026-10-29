"""Repeatable local resource workloads; never contacts a printer or model provider.

Run with the project's Python environment. Peak figures are traced Python
allocations per operation, not process RSS or measurements on a printer host.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Callable

from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.domain.investigation import (
    Investigation,
    InvestigationResult,
    InvestigationTurn,
)
from klipperai_agent.domain.knowledge import CachedDocument
from klipperai_agent.infrastructure.host.logs import HostLogCollector
from klipperai_agent.infrastructure.investigations import SqliteInvestigationRepository
from klipperai_agent.knowledge.retrieval import search_documents


def measure(operation: Callable[[], object], repeats: int) -> dict[str, float]:
    durations, peaks = [], []
    for _ in range(repeats):
        gc.collect()
        tracemalloc.start()
        start = time.perf_counter()
        operation()
        durations.append(time.perf_counter() - start)
        peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    return {
        "median_ms": round(statistics.median(durations) * 1000, 3),
        "peak_python_mib": round(max(peaks) / 1024**2, 3),
    }


def workloads(root: Path) -> dict[str, Callable[[], object]]:
    log = root / "long-line.log"
    with log.open("wb") as handle:
        for _ in range(16):
            handle.write(b"x" * 1024**2)
        handle.write(b"\nLost communication with MCU\n")
    config = root / "printer" / "config"
    config.mkdir(parents=True)
    (config / "printer.cfg").write_text("[printer]\nkinematics: cartesian\n", encoding="utf-8")
    for index in range(500):
        (config / f"backup-{index}.cfg").write_text("# historical backup\n" * 100, encoding="utf-8")
    collector = ConfigCollector(root / "printer", max_documents=100, max_chars_per_document=24000)
    repository = SqliteInvestigationRepository(root / "data", protected_dirs=(config,))
    for index in range(30):
        record = Investigation(printer_id="benchmark", title=f"Saved investigation {index}")
        for _ in range(3):
            repository.save_turn(
                record,
                InvestigationTurn(
                    question="Investigate the printer",
                    result=InvestigationResult(response_text="Observed printer evidence. " * 1600),
                ),
            )
            record = repository.get("benchmark", record.id)
            assert record is not None
    documents = [
        CachedDocument(
            id=f"{index:032x}",
            component_key="example",
            title="Example manual",
            url="https://example.org/manual",
            digest="a" * 64,
            fetched_at="2026-01-01T00:00:00Z",
            kind="text",
            content="printer connector evidence\n" * 10000,
        )
        for index in range(12)
    ]
    summary_reader = getattr(repository, "summaries", repository.recent)
    return {
        "tail_16mib_long_line": lambda: HostLogCollector._read_last_lines(log, 100),
        "config_with_500_backups": collector.collect,
        "sidebar_30_investigations": lambda: summary_reader("benchmark"),
        "search_12_manuals": lambda: search_documents(
            documents, "printer connector evidence", {doc.id for doc in documents}
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="klipperai-resource-benchmark-") as directory:
        results = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "measurement": "operation time and peak traced Python allocations; synthetic local data",
            "workloads": {
                name: measure(operation, options.repeats)
                for name, operation in workloads(Path(directory)).items()
            },
        }
    rendered = json.dumps(results, indent=2)
    if options.output:
        options.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
