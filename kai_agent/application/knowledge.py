"""User-triggered per-printer research; model tools receive only the read-only port."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from kai_agent.agent.ports import ConfigReader, PrinterReader
from kai_agent.application.hardware_validation import validate_hardware
from kai_agent.application.knowledge_observations import (
    connector_observations,
    record_connector,
    record_diagram,
)
from kai_agent.application.knowledge_refresh import cache_source, component_sources
from kai_agent.domain.hardware import ConnectorObservation, DiagramNote
from kai_agent.domain.investigation import utc_now
from kai_agent.domain.knowledge import (
    CachedDocument,
    ComponentIdentity,
    DocumentationFetcher,
    DocumentationResolver,
    KnowledgeConflict,
    KnowledgeRepository,
    KnowledgeResearcher,
    KnowledgeSetup,
)
from kai_agent.domain.redaction import redact_text
from kai_agent.knowledge.buses import bus_evidence
from kai_agent.knowledge.firmware import firmware_sources
from kai_agent.knowledge.identity import component_status, profile_setup, reference_metadata
from kai_agent.knowledge.sources import (
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
        resolver: DocumentationResolver | None = None,
    ):
        self._repository = repository
        self._fetcher = fetcher
        self._resolver = resolver
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
        setup = setup.copy(
            update={
                "facts": redact_text(setup.facts),
                "components": [
                    item.copy(update={"details": redact_text(item.details)})
                    for item in setup.components
                ],
            }
        )
        docs = [
            doc
            for doc in await asyncio.to_thread(self._repository.documents)
            if doc.id not in setup.dismissed_documents
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
            "documents": [reference_metadata(setup, doc) for doc in docs],
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
                    "components": [
                        item.copy(update={"details": redact_text(item.details)})
                        for item in setup.components
                    ],
                    "reviewed_fan_mappings": previous.reviewed_fan_mappings,
                    "reviewed_bus_mappings": previous.reviewed_bus_mappings
                    if (previous.firmware_repository, previous.firmware_commit)
                    == (setup.firmware_repository, setup.firmware_commit)
                    else {},
                    "connectors": previous.connectors,
                    "diagram_notes": previous.diagram_notes,
                    "validation": previous.validation,
                    "confirmed_documents": previous.confirmed_documents,
                    "dismissed_documents": previous.dismissed_documents,
                }
            )
            saved = await asyncio.to_thread(self._repository.save_setup, updated)
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

    async def start_refresh(self, role: str | None = None) -> dict:
        async with self._lock:
            if self._task and not self._task.done():
                if role != self.job.get("component_role"):
                    raise KnowledgeConflict(
                        "Another research job is running. Wait for it to finish."
                    )
                return dict(self.job)
            setup, docs, _ = await self.read()
            if role is not None and not any(item.role == role for item in setup.components):
                raise KnowledgeConflict("This component no longer exists. Reload printer details.")
            components = [
                item
                for item in setup.components
                if (role is None or item.role == role)
                and (
                    item.model.strip().casefold() not in {"", "none", "unknown"}
                    or item.details.strip()
                    or item.integrated_into
                )
            ]
            if role is not None and not components:
                raise KnowledgeConflict("Enter a component model or details before researching it.")
            self.job = {
                "state": "running",
                "completed": 0,
                "total": len(components),
                "message": "Researching your printer components.",
                "changes": [],
                "component_role": role,
            }
            self._task = asyncio.create_task(
                self._run(setup, components, {doc.id: doc for doc in docs}, role is None)
            )
            return dict(self.job)

    async def review_reference(
        self, document_id: str, digest: str, revision: int, *, delete: bool = False
    ) -> KnowledgeSetup:
        async with self._lock:
            self._idle()
            setup, docs, _ = await self.read()
            document = next((item for item in docs if item.id == document_id), None)
            if setup.revision != revision or document is None or document.digest != digest:
                raise KnowledgeConflict("This reference changed. Reload before reviewing it.")
            return await asyncio.to_thread(
                self._repository.update_reference, setup, document, delete=delete
            )

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
        include_firmware: bool = True,
    ) -> None:
        try:
            await asyncio.wait_for(
                self._refresh(setup, components, previous, include_firmware), timeout=600
            )
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
        include_firmware: bool = True,
    ) -> None:
        failed = False
        for component in components:
            self.job["message"] = f"Researching {component.model}"
            try:
                await self._component(component, setup, previous)
            except Exception:
                failed = True
                self.job["changes"].append(
                    f"{component.model or component.role}: research incomplete; cached evidence retained. Check component details and provider/search configuration."
                )
            self.job["completed"] += 1
        for source in firmware_sources(setup) if include_firmware else []:
            if source.id in setup.dismissed_documents:
                continue
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
        sources, discovery_failed = await component_sources(
            component, setup, self.researcher, self._resolver
        )
        if discovery_failed:
            self.job["changes"].append(
                f"{component.role}: discovery or repository traversal incomplete; refreshing available references."
            )
        if not sources:
            raise ValueError("No component documentation found.")
        failed = False
        for source in sources:
            # Rebind provider-discovered data to this component; no provider IDs are trusted.
            checked = document_source(component, source.url, source.title)
            source = replace(
                source, id=checked.id, component_key=checked.component_key, url=checked.url
            )
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
        if failed or discovery_failed:
            raise ValueError("Incomplete source refresh.")

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
