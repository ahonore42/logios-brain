"""Evidence layer: reasoning traces for AI outputs."""

from app.db.neo4j.client import get_driver


def create_evidence_path(
    evidence_path_id: str,
    output_id: str,
    tenant_id: str,
    agent_id: str | None,
    query_hash: str,
    machine_id: str | None,
    used_memory_ids: list[str],
    used_edge_types: list[str],
    timestamp: str,
    timeout: float | None = None,
) -> None:
    """
    Create a full evidence path atomically.

    Creates the EvidencePath node, USED links to each memory, and FOLLOWED
    links to Edge nodes for each edge type that was traversed.
    """
    driver = get_driver()
    with driver.session() as session:
        with session.begin_transaction() as tx:
            tx.run(
                """
                MERGE (e:EvidencePath {id: $id})
                SET e.output_id = $output_id,
                    e.tenant_id = $tenant_id,
                    e.agent_id = $agent_id,
                    e.query_hash = $query_hash,
                    e.machine_id = $machine_id,
                    e.timestamp = $timestamp
                """,
                id=evidence_path_id,
                output_id=output_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                query_hash=query_hash,
                machine_id=machine_id,
                timestamp=timestamp,
            )

            for memory_id in used_memory_ids:
                tx.run(
                    """
                    MERGE (ep:EvidencePath {id: $ep_id})
                    MERGE (m:MemoryChunk {id: $memory_id})
                    MERGE (ep)-[:USED]->(m)
                    """,
                    ep_id=evidence_path_id,
                    memory_id=memory_id,
                )

            for edge_type in used_edge_types:
                tx.run(
                    """
                    MERGE (ep:EvidencePath {id: $ep_id})
                    MERGE (edge:Edge {type: $edge_type})
                    MERGE (ep)-[:FOLLOWED]->(edge)
                    """,
                    ep_id=evidence_path_id,
                    edge_type=edge_type,
                )
            tx.commit()


def add_evidence_step(
    evidence_path_id: str,
    step_id: str,
    step_type: str,
    order: int,
    prev_step_id: str | None = None,
    timeout: float | None = None,
) -> None:
    """
    Add a step to an evidence path.

    If prev_step_id is provided, links the new step as NEXT after it,
    building an ordered reasoning chain.
    """
    driver = get_driver()
    with driver.session() as session:
        with session.begin_transaction() as tx:
            tx.run(
                """
                MERGE (s:EvidenceStep {id: $id})
                SET s.step_type = $step_type,
                    s.order = $order
                """,
                id=step_id,
                step_type=step_type,
                order=order,
            )

            tx.run(
                """
                MERGE (ep:EvidencePath {id: $path_id})
                MERGE (s:EvidenceStep {id: $step_id})
                MERGE (ep)-[:BELONGS_TO]->(s)
                """,
                path_id=evidence_path_id,
                step_id=step_id,
            )

            if prev_step_id:
                tx.run(
                    """
                    MERGE (prev:EvidenceStep {id: $prev_id})
                    MERGE (next:EvidenceStep {id: $next_id})
                    MERGE (prev)-[:NEXT]->(next)
                    """,
                    prev_id=prev_step_id,
                    next_id=step_id,
                )
            tx.commit()


def link_evidence_to_output(
    evidence_path_id: str,
    output_id: str,
    agent_id: str | None,
    tenant_id: str,
    timeout: float | None = None,
) -> None:
    """
    Link an EvidencePath to its Output and Agent.

    Creates:
    - EvidencePath → [:PRODUCED] → Output
    - EvidencePath → [:GENERATED_BY] → Agent (if agent_id provided)
    - EvidencePath → [:BELONGS_TO] → Tenant
    """
    driver = get_driver()
    with driver.session() as session:
        with session.begin_transaction() as tx:
            tx.run(
                """
                MERGE (ep:EvidencePath {id: $ep_id})
                MERGE (o:Output {id: $output_id})
                MERGE (ep)-[:PRODUCED]->(o)
                """,
                ep_id=evidence_path_id,
                output_id=output_id,
            )

            if agent_id:
                tx.run(
                    """
                    MERGE (ep:EvidencePath {id: $ep_id})
                    MERGE (a:Agent {id: $agent_id})
                    MERGE (ep)-[:GENERATED_BY]->(a)
                    """,
                    ep_id=evidence_path_id,
                    agent_id=agent_id,
                )

            tx.run(
                """
                MERGE (ep:EvidencePath {id: $ep_id})
                MERGE (t:Tenant {id: $tenant_id})
                MERGE (ep)-[:BELONGS_TO]->(t)
                """,
                ep_id=evidence_path_id,
                tenant_id=tenant_id,
            )
            tx.commit()
