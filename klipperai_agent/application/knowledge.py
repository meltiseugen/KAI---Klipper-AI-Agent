"""User-triggered per-printer research; model tools receive only the read-only port."""

from __future__ import annotations

import asyncio

from klipperai_agent.agent.ports import ConfigReader, PrinterReader
from klipperai_agent.application.hardware_validation import validate_hardware
from klipperai_agent.application.knowledge_observations import (
    connector_observations,
    record_connector,
    record_diagram,
)
from klipperai_agent.application.knowledge_refresh import cache_source
from klipperai_agent.domain.hardware import ConnectorObservation, DiagramNote
from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.knowledge import (
    CachedDocument,
    ComponentIdentity,
    DocumentationFetcher,
    KnowledgeConflict,
    KnowledgeRepository,
    KnowledgeResearcher,
    KnowledgeSetup,
)
from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.knowledge.buses import bus_evidence
from klipperai_agent.knowledge.firmware import firmware_key, firmware_sources
from klipperai_agent.knowledge.identity import component_status, profile_setup
from klipperai_agent.knowledge.sources import (
    component_key,
    document_source,
    mapping_evidence,
)


class PrinterKnowledge:
    def __init__(
        self,
        repository: KnowledgeRepository,
        fetcher: DocumentationFetcher,
        profile: dict,
        researcher: KnowledgeResearcher | None = None,
        printer: PrinterReader | None = None,
        config: ConfigReader | None = None,
    ):
        self._repository = repository
        self._fetcher = fetcher
        self._seed = profile_setup(profile)
        self.researcher = researcher
        self._printer, self._config = printer, config
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.job: dict = {
            "state": "idle",
            "completed": 0,
            "total": 0,
            "message": "Build knowledge for the components in your printer profile.",
            "changes": [],
        }

    async def read(self) -> tuple[KnowledgeSetup, list[CachedDocument], bool]:
        setup = await asyncio.to_thread(self._repository.setup) or self._seed.copy(deep=True)
        setup = setup.copy(update={"facts": redact_text(setup.facts)})
        keys = {component_key(item) for item in setup.components}
        if setup.firmware_commit:
            keys.add(firmware_key(setup))
        docs = [
            doc
            for doc in await asyncio.to_thread(self._repository.documents)
            if doc.component_key in keys
        ]
        return setup, docs, setup.profile_signature != self._seed.profile_signature

    async def status(self) -> dict:
        setup, docs, changed = await self.read()
        return {
            "setup": setup.model_dump(),
            "profile_changed": changed,
            "components": [
                component_status(
                    item, docs, changed, setup.reviewed_fan_mappings.get(item.role, "")
                )
                for item in setup.components
            ],
            "documents": [
                doc.model_dump(
                    exclude={"content": True, "fan_mappings": True, "pages": {"__all__": {"text"}}}
                )
                for doc in docs
            ],
            "connector_inventory": {
                item.role: connector_observations(setup, item) for item in setup.components
            },
            "bus_evidence": {item.role: bus_evidence(item, docs) for item in setup.components},
            "automatic_research": self.researcher is not None,
            "job": dict(self.job),
        }

    def _idle(self) -> None:
        if self._task and not self._task.done():
            raise KnowledgeConflict(
                "Wait for the documentation refresh before editing component details."
            )

    async def save(self, setup: KnowledgeSetup) -> KnowledgeSetup:
        async with self._lock:
            self._idle()
            previous, _, _ = await self.read()
            updated = setup.copy(
                update={
                    "profile_signature": self._seed.profile_signature,
                    "updated_at": utc_now(),
                    "facts": redact_text(setup.facts),
                    "reviewed_fan_mappings": previous.reviewed_fan_mappings,
                    "reviewed_bus_mappings": previous.reviewed_bus_mappings
                    if (previous.firmware_repository, previous.firmware_commit)
                    == (setup.firmware_repository, setup.firmware_commit)
                    else {},
                    "connectors": previous.connectors,
                    "diagram_notes": previous.diagram_notes,
                    "validation": previous.validation,
                }
            )
            saved = await asyncio.to_thread(self._repository.save_setup, updated)
            await asyncio.to_thread(
                self._repository.retain_components,
                {component_key(item) for item in saved.components}
                | ({firmware_key(saved)} if saved.firmware_commit else set()),
            )
            return saved

    async def review_mappings(self, role: str, signature: str, revision: int) -> KnowledgeSetup:
        async with self._lock:
            self._idle()
            setup, docs, changed = await self.read()
            component = next((item for item in setup.components if item.role == role), None)
            if setup.revision != revision or changed:
                raise KnowledgeConflict(
                    "Printer details changed. Reload before reviewing connector evidence."
                )
            if (
                not component
                or not component.confirmed
                or not component.revision
                or component.category != "board"
            ):
                raise KnowledgeConflict(
                    "Confirm the exact board identity and hardware revision first."
                )
            evidence = mapping_evidence(component, docs)
            if not signature or signature != evidence["signature"] or evidence["conflicts"]:
                raise KnowledgeConflict(
                    "Connector evidence is missing, conflicting or changed. Reload and review its sources."
                )
            return await asyncio.to_thread(
                self._repository.save_setup,
                setup.copy(
                    update={
                        "reviewed_fan_mappings": {**setup.reviewed_fan_mappings, role: signature},
                        "updated_at": utc_now(),
                    }
                ),
            )

    async def start_refresh(self) -> dict:
        async with self._lock:
            if self._task and not self._task.done():
                return dict(self.job)
            setup, docs, _ = await self.read()
            components = [item for item in setup.components if item.model.strip()]
            self.job = {
                "state": "running",
                "completed": 0,
                "total": len(components),
                "message": "Researching your printer components.",
                "changes": [],
            }
            self._task = asyncio.create_task(
                self._run(setup, components, {doc.id: doc for doc in docs})
            )
            return dict(self.job)

    async def review_buses(self, role: str, signature: str, revision: int) -> KnowledgeSetup:
        async with self._lock:
            self._idle()
            setup, docs, changed = await self.read()
            component = next((item for item in setup.components if item.role == role), None)
            evidence = bus_evidence(component, docs) if component else {}
            if (
                setup.revision != revision
                or changed
                or not component
                or not component.confirmed
                or not component.revision
                or not signature
                or evidence.get("signature") != signature
                or evidence.get("conflicts")
            ):
                raise KnowledgeConflict(
                    "Confirm exact hardware/firmware bus evidence, reload, and review the current non-conflicting pinmux sources."
                )
            return await asyncio.to_thread(
                self._repository.save_setup,
                setup.copy(
                    update={
                        "reviewed_bus_mappings": {**setup.reviewed_bus_mappings, role: signature}
                    }
                ),
            )

    async def observe(
        self, observation: ConnectorObservation | DiagramNote, revision: int
    ) -> KnowledgeSetup:
        async with self._lock:
            self._idle()
            setup, docs, changed = await self.read()
            if revision != setup.revision or changed:
                raise KnowledgeConflict(
                    "Printer details changed; reload before confirming an observation."
                )
            updated = (
                record_connector(setup, observation)
                if isinstance(observation, ConnectorObservation)
                else record_diagram(setup, observation, docs)
            )
            return await asyncio.to_thread(self._repository.save_setup, updated)

    async def validate_live(self) -> dict:
        async with self._lock:
            self._idle()
            setup, _, _ = await self.read()
            report = await validate_hardware(setup, self._printer, self._config)
            await asyncio.to_thread(
                self._repository.save_setup, setup.copy(update={"validation": report})
            )
            return report

    async def _run(
        self,
        setup: KnowledgeSetup,
        components: list[ComponentIdentity],
        previous: dict[str, CachedDocument],
    ) -> None:
        try:
            await asyncio.wait_for(self._refresh(setup, components, previous), timeout=600)
        except TimeoutError:
            self.job.update(
                state="partial",
                message="Research time limit reached. Cached evidence was retained; refresh again to retry.",
            )

    async def _refresh(
        self,
        setup: KnowledgeSetup,
        components: list[ComponentIdentity],
        previous: dict[str, CachedDocument],
    ) -> None:
        failed = False
        for component in components:
            self.job["message"] = f"Researching {component.model}"
            try:
                await self._component(component, setup, previous)
            except Exception:
                failed = True
                self.job["changes"].append(
                    f"{component.model}: research incomplete; cached evidence retained. Check public model details, source URLs and provider/search configuration."
                )
            self.job["completed"] += 1
        for source in firmware_sources(setup):
            try:
                change = await cache_source(
                    self._repository, self._fetcher, None, source, previous, firmware=setup
                )
                self.job["changes"].append(f"{source.title}: {change}.")
            except Exception:
                failed = True
                self.job["changes"].append(
                    f"{source.title}: exact-commit reference unavailable; no floating-branch fallback was used."
                )
        self.job.update(
            state="partial" if failed else "completed",
            message="Some component research needs attention."
            if failed
            else "Knowledge refreshed. Review source suitability and any connector evidence."
            if components
            else "Enter component models from your printer profile first.",
        )

    async def _component(
        self,
        component: ComponentIdentity,
        setup: KnowledgeSetup,
        previous: dict[str, CachedDocument],
    ) -> None:
        if component.reference_urls:
            sources = [document_source(component, url) for url in component.reference_urls]
        elif self.researcher:
            sources = await asyncio.wait_for(self.researcher.discover(component, setup), timeout=90)
        else:
            raise ValueError("Automatic research is unavailable; supply public documentation URLs.")
        sources = list({source.id: source for source in sources}.values())[:3]
        if not sources:
            raise ValueError("No component documentation found.")
        failed = False
        for source in sources:
            # Rebind provider-discovered data to this component; no provider IDs are trusted.
            source = document_source(component, source.url, source.title)
            self.job["message"] = f"Reading {component.model}: {source.title}"
            try:
                change = await cache_source(
                    self._repository, self._fetcher, self.researcher, source, previous, component
                )
                self.job["changes"].append(f"{source.title}: {change}.")
            except Exception:
                failed = True
                self.job["changes"].append(
                    f"{source.title}: download or extraction unavailable; existing documents retained."
                )
        if failed:
            raise ValueError("Incomplete source refresh.")
        await asyncio.to_thread(
            self._repository.retain_sources,
            component_key(component),
            {document_source(component, source.url).id for source in sources},
        )

    async def original(self, document_id: str) -> tuple[CachedDocument, bytes] | None:
        _, docs, _ = await self.read()
        doc = next((doc for doc in docs if doc.id == document_id), None)
        original = (
            await asyncio.to_thread(self._repository.original, document_id, doc.digest)
            if doc
            else None
        )
        return (doc, original) if doc and original is not None else None

    async def aclose(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
