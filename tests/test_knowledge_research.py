import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

import klipperai_agent.infrastructure.documentation as download_module
import klipperai_agent.infrastructure.public_docs as network_module
from klipperai_agent.agent.models import SearchResult
from klipperai_agent.domain.evidence import SourceCitation
from klipperai_agent.domain.knowledge import ComponentIdentity, FanMapping
from klipperai_agent.infrastructure.documentation import (
    PublicDocumentationFetcher,
    extract_document,
)
from klipperai_agent.infrastructure.public_docs import public_target, resolve_addresses
from klipperai_agent.knowledge.fans import inspect_fan_ports
from klipperai_agent.knowledge.pins import pin_ownership
from klipperai_agent.knowledge.sources import (
    component_key,
    document_source,
    grounded_mapping,
    mapping_evidence,
)
from klipperai_agent.providers.knowledge import OpenAIKnowledgeResearcher, public_identity
from tests.knowledge_helpers import documents, setup, snapshot


def test_generic_sources_identity_scoping_and_review_invalidations():
    component = setup().components[0]
    source = document_source(component, " https://EXAMPLE.org/manual#fan ", "Reference")
    assert source.url == "https://example.org/manual"
    assert source.id == document_source(component, source.url).id
    assert document_source(component, "https://example.org").url.endswith("/")
    assert (
        document_source(
            component, "https://github.com/vendor/board/blob/main/manual.pdf?raw=true#page=2"
        ).url
        == "https://raw.githubusercontent.com/vendor/board/main/manual.pdf"
    )
    for url in (
        "http://example.org/",
        "https://user:pass@example.org/",
        "https://example.org:8443/",
        "https:///file",
        "https://example.org/" + "x" * 2048,
    ):
        with pytest.raises(ValueError):
            document_source(component, url)
    assert component_key(component) == component_key(
        component.copy(update={"model": " example board a "})
    )
    docs = documents()
    signature = mapping_evidence(component, docs)["signature"]
    assert inspect_fan_ports(component, docs, False, snapshot())["ports"][0]["pin"] is None
    docs[0].fetched_at = "tomorrow"
    assert mapping_evidence(component, docs)["signature"] == signature
    for change in (
        {"mcu": "new"},
        {"connection": "UART"},
        {"confirmed": False},
        {"revision": "new"},
    ):
        assert mapping_evidence(component.copy(update=change), docs)["signature"] != signature
    conflict = FanMapping(connector="FAN0", pin="PB2", quote="FAN0 pin PB2")
    docs[0].content += "\nFAN0 pin PB2"
    docs[0].fan_mappings.append(conflict)
    assert mapping_evidence(component, docs)["conflicts"] == ["fan0"]
    assert "Sources disagree" in str(
        inspect_fan_ports(component, docs, False, snapshot(), signature)
    )
    assert not grounded_mapping(FanMapping(connector="FAN0", pin="PB2", quote="made up"), docs[0])
    assert not grounded_mapping(
        FanMapping(connector="FAN0", pin="PA8", quote="FAN0 pin PA80"),
        docs[0].copy(update={"content": "FAN0 pin PA80"}),
    )


def test_multiple_mcu_pin_syntaxes_and_implicit_i2c_reservations():
    cfg = snapshot(
        "[fan]\npin: P2.4\n[heater_fan extra]\npin: gpio16\n[mcp4451 stepper_digipot]\ni2c_address: 44"
    )
    ownership = pin_ownership(cfg)
    assert not ownership["gaps"]
    assert set(ownership["owners"]) == {"mcu:P2.4", "mcu:gpio16"}
    assert ownership["buses"][0]["mcu"] == "mcu"
    assert FanMapping(connector="FAN0", pin="P2.4", quote="FAN0 P2.4").pin == "P2.4"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "Creality KE board",
        "Qidi Plus 4 board",
        "SV08 board, manufacturer uncertain",
        "An entirely new controller",
    ],
)
async def test_discovery_has_no_hardware_allowlist_and_sends_only_public_identity(model):
    data = setup()
    data.facts = "private-wiring-details"
    component = data.components[0].copy(update={"model": model, "mcu": "private_mcu"})
    citations = [
        SourceCitation(label="source", path=url)
        for url in [
            "http://local/",
            "https://example.org/a",
            "https://example.org/a",
            "https://example.org/b",
            "https://example.org/c",
            "https://example.org/d",
        ]
    ]
    search = SimpleNamespace(
        search=AsyncMock(
            return_value=SearchResult(summary="https://invented.example/", citations=citations)
        )
    )
    client = SimpleNamespace(create=AsyncMock())
    sources = await OpenAIKnowledgeResearcher(client, search).discover(component, data)
    assert [source.url for source in sources] == [
        "https://example.org/a",
        "https://example.org/b",
        "https://example.org/c",
    ]
    query = search.search.call_args.args[0]
    assert model in query and "private" not in query
    client.create.assert_not_awaited()
    with pytest.raises(ValueError, match="public product"):
        public_identity(component.copy(update={"model": "Board at 192.168.1.1"}))


@pytest.mark.asyncio
async def test_extraction_requires_verbatim_connector_and_pin_and_never_uses_tools():
    component, doc = setup().components[0], documents()[0]
    good = doc.fan_mappings[0]
    hallucinated = good.copy(update={"pin": "PB9"})
    output = [
        {"type": "reasoning", "content": "not public"},
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": json.dumps(
                        {"fan_mappings": [good.model_dump(), hallucinated.model_dump()]}
                    ),
                }
            ],
        },
    ]
    client = SimpleNamespace(create=AsyncMock(return_value=output))
    research = OpenAIKnowledgeResearcher(client, SimpleNamespace())
    assert await research.extract(component, doc) == [good]
    kwargs = client.create.call_args.kwargs
    assert kwargs["tools"] == [] and "untrusted" in kwargs["instructions"]
    assert "private_mcu" not in kwargs["input"]
    await research.extract(component, doc.copy(update={"content": doc.content + "x" * 50000}))
    sent = json.loads(client.create.call_args.kwargs["input"])
    assert sent["excerpt_truncated"] and len(sent["text_excerpt"]) == 45000
    assert await research.extract(component, doc.copy(update={"content": ""})) == []
    assert await research.extract(component.copy(update={"category": "probe"}), doc) == []
    client.create.return_value = [
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": '{"fan_mappings":[{"connector":"x","pin":"shell:restart","quote":"x"}]}',
                }
            ],
        }
    ]
    with pytest.raises(ValidationError):
        await research.extract(component, doc)


@pytest.mark.asyncio
async def test_dns_resolution_and_public_target_validation(monkeypatch):
    monkeypatch.setattr(
        network_module.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("1.1.1.1", 443)), (0, 0, 0, "", ("1.1.1.1", 443))],
    )
    assert await resolve_addresses("example.org") == ["1.1.1.1"]
    target, host = public_target("https://example.org/manual#fan", ["1.1.1.1"])
    assert str(target) == "https://1.1.1.1/manual" and host == "example.org"
    for addresses in (
        [],
        ["127.0.0.1"],
        ["192.168.1.10"],
        ["169.254.169.254"],
        ["::1"],
        ["1.1.1.1", "10.0.0.2"],
        ["224.0.0.1"],
    ):
        with pytest.raises(ValueError, match="blocked"):
            public_target("https://example.org", addresses)
    for url in (
        "file:///etc/passwd",
        "http://example.org",
        "https://user:pass@example.org",
        "https://example.org:1234",
    ):
        with pytest.raises(ValueError, match="HTTPS"):
            public_target(url, ["1.1.1.1"])


@pytest.mark.asyncio
async def test_public_fetcher_pins_dns_tls_redirects_and_bounds(monkeypatch):
    client_type = httpx.AsyncClient
    reply = {"status": 200, "content": b"reference", "headers": {}}
    requests, options = [], []

    def respond(request):
        requests.append(request)
        return httpx.Response(reply["status"], content=reply["content"], headers=reply["headers"])

    def client(**kwargs):
        options.append(kwargs)
        return client_type(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(download_module.httpx, "AsyncClient", client)
    resolver = AsyncMock(return_value=["1.1.1.1"])
    fetcher = PublicDocumentationFetcher(resolver)
    source = document_source(ComponentIdentity(role="aux"), "https://example.org/manual")
    assert await fetcher.fetch(source) == (b"reference", "reference", "text")
    assert options[0]["trust_env"] is False and options[0]["follow_redirects"] is False
    assert requests[0].url.host == "1.1.1.1" and requests[0].headers["Host"] == "example.org"
    assert requests[0].extensions["sni_hostname"] == "example.org"
    assert requests[0].headers["accept-encoding"] == "identity"
    reply.update(
        status=302,
        content=b"",
        headers={"location": "https://other.example/doc", "set-cookie": "private=value"},
    )
    resolver.side_effect = [["1.1.1.1"], ["127.0.0.1"]]
    count = len(requests)
    with pytest.raises(ValueError, match="blocked"):
        await fetcher.fetch(source)
    assert len(requests) == count + 1
    resolver.side_effect = None
    with pytest.raises(ValueError, match="Too many"):
        await fetcher.fetch(source)
    assert all("cookie" not in request.headers for request in requests)
    reply.update(status=404, headers={})
    with pytest.raises(httpx.HTTPStatusError):
        await fetcher.fetch(source)
    reply.update(status=200, headers={"content-encoding": "identity, identity"})
    with pytest.raises(ValueError, match="Compressed"):
        await fetcher.fetch(source)
    reply.update(headers={}, content=b"x" * (8 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="download size"):
        await fetcher.fetch(source)
    with pytest.raises(ValueError, match="HTTPS"):
        await fetcher.fetch(replace(source, url="http://localhost/secret"))


def test_document_formats_and_text_bounds():
    html = b"<html><style>hidden</style><h1>Board</h1><script>evil()</script><pre>FAN0 PA8</pre></html>"
    text, kind = extract_document(html, "text/html")
    assert (
        kind == "html"
        and "Board" in text
        and "FAN0 PA8" in text
        and "evil" not in text
        and "hidden" not in text
    )
    for data, expected in (
        (b"%PDF-1.4 test", "pdf"),
        (b"\x89PNG\r\n\x1a\n", "image"),
        (b"\xff\xd8\xffx", "jpeg"),
    ):
        assert extract_document(data, "") == ("", expected)
    for data, content_type, message in (
        (b"not pdf", "application/pdf", "binary"),
        (b"\x00x", "", "binary"),
        (b"", "", "empty"),
        (b"x" * 300001, "", "indexing"),
        (b"x" * 512001, "", "download size"),
    ):
        with pytest.raises(ValueError, match=message):
            extract_document(data, content_type)
