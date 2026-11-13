"""Tests for Sentinel Semantic Vector Memory & Nearest-Neighbor Retrieval."""
from __future__ import annotations

from pathlib import Path

from sentinel_core.vector_index import VectorIndex, FastSemanticVectorizer, cosine_similarity
from sentinel_core.db import SentinelDB
from sentinel_adaptive.mistake_ledger import MistakeMemory


def test_fast_vectorizer_determinism_and_norm():
    vec = FastSemanticVectorizer(dimension=384)
    v1 = vec.vectorize("Synthesize a 3D procedural telescope with brass tripod in Blender")
    v2 = vec.vectorize("Synthesize a 3D procedural telescope with brass tripod in Blender")
    assert len(v1) == 384
    assert v1 == v2
    # Verify unit L2 norm
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-4


def test_cosine_similarity_semantics():
    vec = FastSemanticVectorizer(dimension=384)
    # Semantically close
    v_tele_a = vec.vectorize("astronomical optical telescope with glass lens and brass tube")
    v_tele_b = vec.vectorize("procedural telescope model with optical dew shield and mount")
    # Semantically unrelated
    v_data = vec.vectorize("calculate quarterly revenue accounting ledgers and tax spreadsheets")

    sim_close = cosine_similarity(v_tele_a, v_tele_b)
    sim_far = cosine_similarity(v_tele_a, v_data)

    assert sim_close > sim_far
    assert sim_close > 0.15


def test_vector_index_ranking_and_filtering():
    idx = VectorIndex(dimension=384)
    idx.upsert("tele_1", "3D telescope model asset with optical tube and tripod", metadata={"domain": "3d"})
    idx.upsert("csv_1", "Data analytics CSV dataset generator for financial customers", metadata={"domain": "data"})
    idx.upsert("code_1", "LRU cache implementation in Python with put and get", metadata={"domain": "code"})

    # Query with domain filter
    res_3d = idx.query("synthesize an optical telescope", top_k=2, filter_fn=lambda m: m.get("domain") == "3d")
    assert len(res_3d) == 1
    assert res_3d[0]["id"] == "tele_1"
    assert res_3d[0]["score"] > 0.10


def test_mistake_memory_semantic_vector_retrieval(tmp_path: Path):
    db_path = tmp_path / "test_vec.db"
    db = SentinelDB(db_path)
    with db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('t1', 'T1', 'Failed', 0, 0)")
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('t2', 'T2', 'Failed', 0, 0)")

    mem = MistakeMemory(db)

    # Record mistakes
    mem.record_mistake(
        task_id="t1",
        attempt_id="att1",
        error_category="DEPRECATED_API",
        error_signature="Matrix.Translation deprecated in Blender 4.5",
        context={"domain": "3d"},
        lesson_learned="Use Matrix.LocRotScale or mathutils translation helper in Blender 4.5",
    )
    mem.record_mistake(
        task_id="t2",
        attempt_id="att2",
        error_category="IO_ERROR",
        error_signature="FileNotFoundError csv missing",
        context={"domain": "data"},
        lesson_learned="Ensure parent directory exists before calling open in write mode",
    )

    # Query cross-task lessons with semantic query
    lessons = mem.get_cross_task_lessons(domain="3d", limit=2, query="Blender Matrix transform error")
    assert len(lessons) >= 1
    assert "Matrix" in lessons[0]["lesson_learned"] or "Blender" in lessons[0]["lesson_learned"]
