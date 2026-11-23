"""Expand GitHub index citations through the same bounded public-download boundary."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from hashlib import sha256
from urllib.parse import quote

from kai_agent.domain.knowledge import DocumentationFetcher, DocumentSource
from kai_agent.knowledge.repositories import reference_paths, repository_location


class RepositoryDocumentationResolver:
    def __init__(self, fetcher: DocumentationFetcher):
        self._fetcher = fetcher

    async def _json(self, url: str) -> dict:
        _, text, _ = await self._fetcher.fetch(
            DocumentSource("repository-listing", "Repository listing", url)
        )
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Invalid repository metadata.")
        return data

    async def resolve(self, source: DocumentSource) -> list[DocumentSource]:
        location = repository_location(source.url)
        if location is None:
            return [source]
        repository, ref, prefix = location
        base = "https://api.github.com/repos/" + repository
        commit = await self._json(base + "/commits/" + quote(ref, safe=""))
        revision = commit.get("sha", "")
        if not isinstance(revision, str) or not re.fullmatch("[a-fA-F0-9]{40}", revision):
            raise ValueError("Repository commit is unavailable.")
        tree = await self._json(base + "/git/trees/" + revision + "?recursive=1")
        sources = []
        for path in reference_paths(tree, prefix):
            raw = "https://raw.githubusercontent.com/" + repository + "/"
            url = raw + quote(ref, safe="") + "/" + quote(path, safe="/")
            sources.append(
                replace(
                    source,
                    id=sha256((source.component_key + url).encode()).hexdigest()[:32],
                    title=(repository + " / " + path)[:160],
                    url=url,
                    download_url=raw + revision + "/" + quote(path, safe="/"),
                    repository_commit=revision,
                )
            )
        return sources
