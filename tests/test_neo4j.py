"""Tests for Neo4j graph storage — full schema."""
import hashlib
from uuid import uuid4

import pytest
# import pytest_asyncio  # TODO: needed when async Neo4j tests are added

from app.db.neo4j import (
    create_evidence_path,
    add_evidence_step,
    get_latest_fact,
    get_driver,
    link_evidence_to_output,
    write_event,
    write_fact,
    write_memory_chunk,
    RelationshipType,
    Event,
    EvidenceStep,
    Fact,
    MemoryChunk,
    ensure_indexes,
    # AgentNode, OutputNode, EvidencePath  # TODO: needed for future evidence layer tests
)
from app.db.neo4j.client import prefixed_id, NodeId


@pytest.fixture(scope="module", autouse=True)
def setup_indexes():
    """Ensure Neo4j constraints and indexes exist before tests."""
    try:
        ensure_indexes()
    except Exception:
        pass  # May already exist


@pytest.mark.asyncio
async def test_write_memory_chunk_creates_node():
    """MemoryChunk node should be created with all properties."""
    chunk = MemoryChunk(
        id=prefixed_id(NodeId.MEMORY_CHUNK, str(uuid4())),
        tenant_id="test-tenant",
        timestamp_utc="2024-01-01T00:00:00Z",
        type="manual",
        version=1,
        importance=0.7,
        confidence=0.95,
    )
    event_id = prefixed_id(NodeId.EVENT, str(uuid4()))
    write_memory_chunk(
        chunk=chunk,
        event_id=event_id,
        event_type="manual",
        event_description="Memory captured: manual",
    )

    from app.db.neo4j import get_driver

    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (m:MemoryChunk {id: $id}) RETURN m.id as id, m.type as type, m.importance as importance",
            id=chunk.id,
        )
        record = result.single()
        assert record is not None
        assert record["type"] == "manual"
        assert record["importance"] == 0.7

        # Verify Event node was created and linked via DESCRIBES
        ev = session.run(
            """
            MATCH (e:Event {id: $eid})-[:DESCRIBES]->(m:MemoryChunk {id: $mid})
            RETURN e.type as event_type, e.description as description
            """,
            eid=event_id,
            mid=chunk.id,
        ).single()
        assert ev is not None
        assert ev["event_type"] == "manual"
        assert ev["description"] == "Memory captured: manual"


@pytest.mark.asyncio
async def test_write_memory_chunk_with_session():
    """MemoryChunk with session_id should create IN_SESSION relationship."""
    chunk = MemoryChunk(
        id=prefixed_id(NodeId.MEMORY_CHUNK, str(uuid4())),
        tenant_id="test-tenant",
        timestamp_utc="2024-01-01T00:00:00Z",
        type="telegram",
    )
    session_id = str(uuid4())
    event_id = prefixed_id(NodeId.EVENT, str(uuid4()))
    write_memory_chunk(chunk=chunk, session_id=session_id, event_id=event_id, event_type="telegram", event_description="Memory captured: telegram")

    from app.db.neo4j import get_driver

    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (m:MemoryChunk {id: $mid})-[r:IN_SESSION]->(s:Session {id: $sid})
            RETURN type(r) as rel_type
            """,
            mid=chunk.id,
            sid=session_id,
        )
        record = result.single()
        assert record is not None
        assert record["rel_type"] == "IN_SESSION"


@pytest.mark.asyncio
async def test_write_memory_chunk_is_idempotent():
    """Writing same MemoryChunk twice should not duplicate the node."""
    chunk = MemoryChunk(
        id=prefixed_id(NodeId.MEMORY_CHUNK, str(uuid4())),
        tenant_id="test-tenant",
        timestamp_utc="2024-01-01T00:00:00Z",
        type="manual",
    )
    event_id = prefixed_id(NodeId.EVENT, str(uuid4()))
    write_memory_chunk(chunk=chunk, event_id=event_id, event_type="manual", event_description="Memory captured: manual")
    write_memory_chunk(chunk=chunk)  # second write — MemoryChunk is MERGE, stays idempotent

    from app.db.neo4j import get_driver

    driver = get_driver()
    with driver.session() as session:
        count = session.run(
            "MATCH (m:MemoryChunk {id: $id}) RETURN count(m) as cnt",
            id=chunk.id,
        ).single()["cnt"]
        assert count == 1


@pytest.mark.asyncio
async def test_write_event_creates_node():
    """Event node should be created and linked to a DateNode."""
    event = Event(
        id=prefixed_id(NodeId.EVENT, str(uuid4())),
        tenant_id="test-tenant",
        agent_id=prefixed_id(NodeId.AGENT, str(uuid4())),
        type="meeting",
        description="Quarterly planning session",
        timestamp_utc="2024-06-15T10:00:00Z",
    )
    write_event(event=event, date_str="2024-06-15")

    from app.db.neo4j import get_driver

    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event {id: $id}) RETURN e.type as type, e.description as description
            """,
            id=event.id,
        )
        record = result.single()
        assert record is not None
        assert record["type"] == "meeting"
        assert record["description"] == "Quarterly planning session"


@pytest.mark.asyncio
async def test_write_event_links_to_date():
    """Event should be linked to DateNode via OCCURRED_ON."""
    event = Event(
        id=prefixed_id(NodeId.EVENT, str(uuid4())),
        tenant_id="test-tenant",
        agent_id=None,
        type="decision",
        description="Approved Q3 budget",
        timestamp_utc="2024-06-15T14:00:00Z",
    )
    write_event(event=event, date_str="2024-06-15")

    from app.db.neo4j import get_driver

    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event {id: $id})-[:OCCURRED_ON]->(d:Date)
            RETURN d.date as date
            """,
            id=event.id,
        )
        record = result.single()
        assert record is not None
        assert record["date"] == "2024-06-15"


@pytest.mark.asyncio
async def test_write_fact_creates_node():
    """Fact node should be created with DERIVED_FROM links."""
    source_chunk = MemoryChunk(
        id=prefixed_id(NodeId.MEMORY_CHUNK, str(uuid4())),
        tenant_id="test-tenant",
        timestamp_utc="2024-01-01T00:00:00Z",
        type="conversation",
    )
    write_memory_chunk(chunk=source_chunk)

    fact = Fact(
        id=prefixed_id(NodeId.FACT, str(uuid4())),
        tenant_id="test-tenant",
        content="Client prefers tiered pricing",
        valid_from="2024-01-01T00:00:00Z",
        valid_until="2099-12-31T23:59:59Z",
    )
    write_fact(fact=fact, derived_from_ids=[source_chunk.id])

    from app.db.neo4j import get_driver

    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (f:Fact {id: $id})-[:DERIVED_FROM]->(m:MemoryChunk {id: $src})
            RETURN f.content as content
            """,
            id=fact.id,
            src=source_chunk.id,
        )
        record = result.single()
        assert record is not None
        assert record["content"] == "Client prefers tiered pricing"


@pytest.mark.asyncio
async def test_get_latest_fact_no_replacement():
    """Fact with no outgoing REPLACES edge returns itself."""
    fact = Fact(
        id=prefixed_id(NodeId.FACT, str(uuid4())),
        tenant_id="test-tenant",
        content="Current pricing is $99/month",
        valid_from="2024-01-01T00:00:00Z",
        valid_until="2099-12-31T23:59:59Z",
    )
    write_fact(fact=fact)

    result = get_latest_fact(fact.id)
    assert result is not None
    assert result["id"] == fact.id
    assert result["content"] == "Current pricing is $99/month"


@pytest.mark.asyncio
async def test_get_latest_fact_single_hop():
    """Fact v2 REPLACES v1: querying v1 returns v2."""
    fact_v1 = Fact(
        id=prefixed_id(NodeId.FACT, str(uuid4())),
        tenant_id="test-tenant",
        content="Old: pricing at $49",
        valid_from="2024-01-01T00:00:00Z",
        valid_until="2024-06-01T00:00:00Z",
    )
    fact_v2 = Fact(
        id=prefixed_id(NodeId.FACT, str(uuid4())),
        tenant_id="test-tenant",
        content="New: pricing at $99",
        valid_from="2024-06-01T00:00:00Z",
        valid_until="2099-12-31T23:59:59Z",
    )
    write_fact(fact=fact_v1)
    write_fact(fact=fact_v2)

    # Create REPLACES edge: v2 REPLACES v1
    driver = get_driver()
    with driver.session() as session:
        session.run(
            """
            MATCH (newer:Fact {id: $v2_id}), (older:Fact {id: $v1_id})
            MERGE (newer)-[:REPLACES]->(older)
            """,
            v2_id=fact_v2.id,
            v1_id=fact_v1.id,
        )

    result = get_latest_fact(fact_v1.id)
    assert result is not None
    assert result["id"] == fact_v2.id
    assert result["content"] == "New: pricing at $99"


@pytest.mark.asyncio
async def test_get_latest_fact_multi_hop_chain():
    """Fact v3 REPLACES v2 REPLACES v1: querying v1 returns v3 (chain tip)."""
    fact_v1 = Fact(
        id=prefixed_id(NodeId.FACT, str(uuid4())),
        tenant_id="test-tenant",
        content="v1: initial estimate",
        valid_from="2024-01-01T00:00:00Z",
        valid_until="2024-03-01T00:00:00Z",
    )
    fact_v2 = Fact(
        id=prefixed_id(NodeId.FACT, str(uuid4())),
        tenant_id="test-tenant",
        content="v2: revised estimate",
        valid_from="2024-03-01T00:00:00Z",
        valid_until="2024-06-01T00:00:00Z",
    )
    fact_v3 = Fact(
        id=prefixed_id(NodeId.FACT, str(uuid4())),
        tenant_id="test-tenant",
        content="v3: final estimate",
        valid_from="2024-06-01T00:00:00Z",
        valid_until="2099-12-31T23:59:59Z",
    )
    write_fact(fact=fact_v1)
    write_fact(fact=fact_v2)
    write_fact(fact=fact_v3)

    # Create chain: v2 REPLACES v1, v3 REPLACES v2
    driver = get_driver()
    with driver.session() as session:
        session.run(
            """
            MATCH (v2:Fact {id: $v2_id}), (v1:Fact {id: $v1_id}), (v3:Fact {id: $v3_id})
            MERGE (v2)-[:REPLACES]->(v1)
            MERGE (v3)-[:REPLACES]->(v2)
            """,
            v1_id=fact_v1.id,
            v2_id=fact_v2.id,
            v3_id=fact_v3.id,
        )

    # Querying v1 should return v3 (chain tip), not v2
    result = get_latest_fact(fact_v1.id)
    assert result is not None
    assert result["id"] == fact_v3.id
    assert result["content"] == "v3: final estimate"

    # Querying v2 should also return v3
    result_v2 = get_latest_fact(fact_v2.id)
    assert result_v2 is not None
    assert result_v2["id"] == fact_v3.id

    # Querying v3 should return v3 itself
    result_v3 = get_latest_fact(fact_v3.id)
    assert result_v3 is not None
    assert result_v3["id"] == fact_v3.id


@pytest.mark.asyncio
async def test_get_latest_fact_not_found():
    """Non-existent Fact ID returns None."""
    result = get_latest_fact("nonexistent-fact-id")
    assert result is None


@pytest.mark.asyncio
async def test_create_evidence_path():
    """EvidencePath should be created with USED and FOLLOWED links."""
    # Create a memory chunk first
    chunk = MemoryChunk(
        id=prefixed_id(NodeId.MEMORY_CHUNK, str(uuid4())),
        tenant_id="test-tenant",
        timestamp_utc="2024-01-01T00:00:00Z",
        type="manual",
    )
    write_memory_chunk(chunk=chunk)

    evidence_path_id = prefixed_id(NodeId.EVIDENCE_PATH, str(uuid4()))
    output_id = prefixed_id(NodeId.OUTPUT, str(uuid4()))
    timestamp = "2024-06-15T12:00:00Z"
    query_hash = hashlib.sha256(b"test query").hexdigest()

    create_evidence_path(
        evidence_path_id=evidence_path_id,
        output_id=output_id,
        tenant_id="test-tenant",
        agent_id=None,
        query_hash=query_hash,
        machine_id="test-machine",
        used_memory_ids=[chunk.id],
        used_edge_types=["IN_SESSION", "RELATED_TO"],
        timestamp=timestamp,
    )

    from app.db.neo4j import get_driver

    driver = get_driver()
    with driver.session() as session:
        # Verify EvidencePath exists
        ep = session.run(
            "MATCH (e:EvidencePath {id: $id}) RETURN e.output_id as output_id",
            id=evidence_path_id,
        ).single()
        assert ep is not None
        assert ep["output_id"] == output_id

        # Verify USED link to MemoryChunk
        used = session.run(
            """
            MATCH (e:EvidencePath {id: $id})-[:USED]->(m:MemoryChunk)
            RETURN m.id as memory_id
            """,
            id=evidence_path_id,
        ).single()
        assert used is not None
        assert used["memory_id"] == chunk.id

        # Verify FOLLOWED links to Edge nodes
        followed = session.run(
            """
            MATCH (e:EvidencePath {id: $id})-[:FOLLOWED]->(edge:Edge)
            RETURN collect(edge.type) as edge_types
            """,
            id=evidence_path_id,
        ).single()
        assert followed is not None
        assert set(followed["edge_types"]) == {"IN_SESSION", "RELATED_TO"}


@pytest.mark.asyncio
async def test_add_evidence_step():
    """EvidenceStep should be created and linked with NEXT chain."""
    evidence_path_id = prefixed_id(NodeId.EVIDENCE_PATH, str(uuid4()))

    step1 = EvidenceStep(id=prefixed_id(NodeId.EVIDENCE_STEP, str(uuid4())), step_type="read_memory", order=0)
    step2 = EvidenceStep(id=prefixed_id(NodeId.EVIDENCE_STEP, str(uuid4())), step_type="merge_context", order=1)
    step3 = EvidenceStep(id=prefixed_id(NodeId.EVIDENCE_STEP, str(uuid4())), step_type="generate_output", order=2)

    add_evidence_step(evidence_path_id=evidence_path_id, step_id=step1.id, step_type=step1.step_type, order=step1.order)
    add_evidence_step(evidence_path_id=evidence_path_id, step_id=step2.id, step_type=step2.step_type, order=step2.order, prev_step_id=step1.id)
    add_evidence_step(evidence_path_id=evidence_path_id, step_id=step3.id, step_type=step3.step_type, order=step3.order, prev_step_id=step2.id)

    from app.db.neo4j import get_driver

    driver = get_driver()
    with driver.session() as session:
        # Verify NEXT chain: step1 → step2 → step3
        chain = session.run(
            """
            MATCH (s1:EvidenceStep {id: $id1})-[r:NEXT]->(s2:EvidenceStep {id: $id2})
            RETURN s1.step_type as from_step, s2.step_type as to_step
            """,
            id1=step1.id,
            id2=step2.id,
        ).single()
        assert chain is not None
        assert chain["from_step"] == "read_memory"
        assert chain["to_step"] == "merge_context"


@pytest.mark.asyncio
async def test_link_evidence_to_output():
    """EvidencePath should link to Output via PRODUCED and to Agent via GENERATED_BY."""
    from app.db.neo4j import get_driver

    driver = get_driver()

    # Create an Output node first
    output_id = prefixed_id(NodeId.OUTPUT, str(uuid4()))
    with driver.session() as session:
        session.run(
            "MERGE (o:Output {id: $id}) SET o.tenant_id = $tid, o.type = $type, o.timestamp = $ts",
            id=output_id,
            tid="test-tenant",
            type="analysis",
            ts="2024-06-15T12:00:00Z",
        )

    # Create an Agent node
    agent_id = prefixed_id(NodeId.AGENT, str(uuid4()))
    with driver.session() as session:
        session.run(
            "MERGE (a:Agent {id: $id}) SET a.tenant_id = $tid, a.name = $name, a.role = $role",
            id=agent_id,
            tid="test-tenant",
            name="planner-01",
            role="planner",
        )

    evidence_path_id = prefixed_id(NodeId.EVIDENCE_PATH, str(uuid4()))
    link_evidence_to_output(
        evidence_path_id=evidence_path_id,
        output_id=output_id,
        agent_id=agent_id,
        tenant_id="test-tenant",
    )

    with driver.session() as session:
        # Verify PRODUCED link
        produced = session.run(
            """
            MATCH (e:EvidencePath {id: $ep_id})-[r:PRODUCED]->(o:Output {id: $out_id})
            RETURN type(r) as rel_type
            """,
            ep_id=evidence_path_id,
            out_id=output_id,
        ).single()
        assert produced is not None
        assert produced["rel_type"] == "PRODUCED"

        # Verify GENERATED_BY link
        gen_by = session.run(
            """
            MATCH (e:EvidencePath {id: $ep_id})-[r:GENERATED_BY]->(a:Agent {id: $ag_id})
            RETURN type(r) as rel_type
            """,
            ep_id=evidence_path_id,
            ag_id=agent_id,
        ).single()
        assert gen_by is not None
        assert gen_by["rel_type"] == "GENERATED_BY"


@pytest.mark.asyncio
async def test_relationship_type_enum_values():
    """RelationshipType enum should have all expected values."""
    assert RelationshipType.DESCRIBES.value == "DESCRIBES"
    assert RelationshipType.DERIVED_FROM.value == "DERIVED_FROM"
    assert RelationshipType.REPLACES.value == "REPLACES"
    assert RelationshipType.OVERRIDES.value == "OVERRIDES"
    assert RelationshipType.OCCURRED_ON.value == "OCCURRED_ON"
    assert RelationshipType.APPLIES_DURING.value == "APPLIES_DURING"
    assert RelationshipType.HAPPENED_BEFORE.value == "HAPPENED_BEFORE"
    assert RelationshipType.HAPPENED_AFTER.value == "HAPPENED_AFTER"
    assert RelationshipType.APPLIES_TO.value == "APPLIES_TO"
    assert RelationshipType.REQUIRES.value == "REQUIRES"
    assert RelationshipType.GOVERNS.value == "GOVERNS"
    assert RelationshipType.AUTHORIZED_BY.value == "AUTHORIZED_BY"
    assert RelationshipType.USED.value == "USED"
    assert RelationshipType.FOLLOWED.value == "FOLLOWED"
    assert RelationshipType.PRODUCED.value == "PRODUCED"
    assert RelationshipType.GENERATED_BY.value == "GENERATED_BY"
    assert RelationshipType.BELONGS_TO.value == "BELONGS_TO"
    assert RelationshipType.NEXT.value == "NEXT"
    assert RelationshipType.IN_SESSION.value == "IN_SESSION"
