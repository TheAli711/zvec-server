"""Unit tests for :mod:`zvec_server.adapter.doc_mapper`."""

from __future__ import annotations

from zvec_server.adapter import doc_mapper, runtime
from zvec_server.models.vectors import DocIn

runtime.init_zvec()


class _FakeStatus:
    """Minimal stand-in for a Zvec ``Status``."""

    def __init__(self, ok: bool, code: str, message: str = "") -> None:
        self._ok = ok
        self._code = code
        self._message = message

    def ok(self) -> bool:
        return self._ok

    def code(self) -> _FakeCode:
        return _FakeCode(self._code)

    def message(self) -> str:
        return self._message


class _FakeCode:
    def __init__(self, name: str) -> None:
        self.name = name


def test_to_zvec_doc_preserves_id() -> None:
    zdoc = doc_mapper.to_zvec_doc(DocIn(id="abc", vectors={"emb": [1.0, 2.0]}, fields={"x": 1}))
    assert zdoc.id == "abc"
    assert zdoc.vectors["emb"] == [1.0, 2.0]
    assert zdoc.fields["x"] == 1


def test_to_zvec_doc_autogenerates_uuid() -> None:
    zdoc = doc_mapper.to_zvec_doc(DocIn(vectors={"emb": [1.0]}))
    assert isinstance(zdoc.id, str)
    assert len(zdoc.id) == 32  # uuid4().hex
    int(zdoc.id, 16)  # valid hex


def test_to_zvec_docs_returns_resolved_ids() -> None:
    docs = [DocIn(id="keep", vectors={"emb": [1.0]}), DocIn(vectors={"emb": [2.0]})]
    zdocs, ids = doc_mapper.to_zvec_docs(docs)
    assert len(zdocs) == 2
    assert ids[0] == "keep"
    assert len(ids[1]) == 32
    assert ids[1] == zdocs[1].id  # resolved id matches the doc


def test_status_to_item() -> None:
    item = doc_mapper.status_to_item("doc-1", _FakeStatus(True, "OK", "fine"))
    assert item.id == "doc-1"
    assert item.ok is True
    assert item.code == "OK"
    assert item.message == "fine"


def test_build_write_response_counts() -> None:
    statuses = [
        _FakeStatus(True, "OK"),
        _FakeStatus(False, "INVALID_ARGUMENT", "bad"),
        _FakeStatus(True, "OK"),
    ]
    resp = doc_mapper.build_write_response(["a", "b", "c"], statuses)
    assert resp.success_count == 2
    assert resp.error_count == 1
    assert [r.id for r in resp.results] == ["a", "b", "c"]
    assert resp.results[1].code == "INVALID_ARGUMENT"


def test_from_zvec_doc_round_trip_with_real_doc() -> None:
    import zvec

    zdoc = zvec.Doc(id="r1", score=0.5, vectors={"emb": [1.0, 0.0]}, fields={"cat": "tech"})
    out_with = doc_mapper.from_zvec_doc(zdoc, include_vector=True)
    assert out_with.id == "r1"
    assert out_with.score == 0.5
    assert out_with.vectors == {"emb": [1.0, 0.0]}
    assert out_with.fields == {"cat": "tech"}

    out_without = doc_mapper.from_zvec_doc(zdoc, include_vector=False)
    assert out_without.vectors is None
    assert out_without.fields == {"cat": "tech"}


def test_from_zvec_doc_empty_fields_become_none() -> None:
    import zvec

    zdoc = zvec.Doc(id="r2", vectors={"emb": [1.0]}, fields={})
    out = doc_mapper.from_zvec_doc(zdoc, include_vector=False)
    assert out.fields is None
    assert out.vectors is None
