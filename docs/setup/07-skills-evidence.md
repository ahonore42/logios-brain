# Step 7: Skills and Evidence Layer

This is the most important architectural piece. The skills layer gives your AI reusable reasoning templates. The evidence layer ensures every output comes with a receipt showing exactly what the system was reading when it produced it.

---

## How it works end-to-end

When your local AI invokes `run_skill`:

1. The MCP server loads the skill's prompt template from Supabase
2. It runs a semantic search over Qdrant using the skill context as the query
3. It runs a graph traversal over Neo4j if an entity is specified
4. It returns a **prompt + evidence manifest** to the local AI
5. The local AI executes the prompt against its local model
6. The local AI calls `record_generation` with the output and the evidence manifest
7. The server writes one row to `generations` and one row per source to `evidence`

The receipt is now permanent and queryable. Any future query about "what was the system thinking when it wrote X?" returns the exact ordered list of memories and graph nodes that informed it.

---

## Seeding initial skills

Create this file at `scripts/seed_skills.py` and run it once after your schema is set up.

```python
"""
scripts/seed_skills.py

Seeds the skills table with initial prompt templates.
Run once after schema setup:
  python3 scripts/seed_skills.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from dotenv import load_dotenv
load_dotenv("/opt/logios-brain/.env")

from db.supabase import get_supabase

SKILLS = [
    {
        "name": "memory_migration",
        "description": "Extract and store everything the AI already knows about the user",
        "prompt_template": """
You are a memory migration assistant for a personal AI knowledge system.

Your job: review the evidence context below and the user's instruction,
then produce a clean, structured summary of what should be permanently stored.
Each fact should be a self-contained statement that will make sense to any AI
reading it cold, with no prior context about the user.

Evidence context:
{evidence_context}

User instruction: {user_instruction}

Output a JSON array of memory objects:
[
  {"content": "fact about the user", "source": "migration", "metadata": {}}
]

Return only valid JSON. No markdown, no explanation.
""".strip(),
    },
    {
        "name": "weekly_review",
        "description": "End-of-week synthesis over recent captures",
        "prompt_template": """
You are a personal knowledge analyst reviewing a week of captured memories.

Evidence context (this week's captures):
{evidence_context}

Produce a structured weekly review covering:
1. Top 3-5 themes that dominated this week's thinking
2. Open loops — action items or decisions without resolution
3. Non-obvious connections between captures from different days
4. Gaps — topics that were absent given the user's known priorities
5. Suggested focus for next week

Be direct and specific. No filler. Surface what the user would not notice
in the daily flow. Reference specific captures by content when relevant.

User's current priorities: {user_instruction}
""".strip(),
    },
    {
        "name": "competitive_analysis",
        "description": "Build a competitor brief from stored context",
        "prompt_template": """
You are a strategic analyst with access to the user's personal knowledge base.

Evidence context:
{evidence_context}

Produce a competitive analysis brief covering:
- What the user already knows about this competitor or space
- Key differentiators and weaknesses
- Strategic implications for the user's work
- Open questions and recommended research

Be concrete. Cite what you know from the evidence context.
Do not speculate beyond what is supported by the evidence.

Focus: {user_instruction}
""".strip(),
    },
    {
        "name": "session_capture",
        "description": "Summarize and capture key outputs from a working session",
        "prompt_template": """
You are a session capture assistant. Your job is to extract the permanent knowledge
from this working session and prepare it for storage.

Session content:
{evidence_context}

Extract and format:
1. Decisions made (with reasoning if present)
2. Key insights or reframes
3. Action items with owners and dates if mentioned
4. New concepts or techniques learned
5. People mentioned with relevant context

Format as a JSON array of memory objects ready for storage:
[
  {
    "content": "self-contained statement",
    "source": "system",
    "metadata": {"type": "decision|insight|action|concept|person"}
  }
]

Return only valid JSON.
""".strip(),
    },
    {
        "name": "research_synthesis",
        "description": "Synthesize a set of sources into findings with confidence markers",
        "prompt_template": """
You are a research synthesis assistant with access to stored knowledge.

Evidence context:
{evidence_context}

Synthesize the evidence into:
- Core findings (what the evidence clearly supports)
- Contradictions or tensions in the evidence
- Confidence assessment for each finding (high/medium/low and why)
- Open questions the evidence does not resolve
- Recommended next research steps

Cite your sources by referencing specific captures.
Mark low-confidence claims explicitly.

Research question: {user_instruction}
""".strip(),
    },
    {
        "name": "deal_memo",
        "description": "Draft a deal or partnership memo from stored diligence",
        "prompt_template": """
You are a deal memo writer with access to the user's research and notes.

Evidence context:
{evidence_context}

Draft a structured deal memo covering:
- Opportunity summary
- Key facts from diligence
- Risks and open questions
- Recommendation with rationale
- Next steps

Write in plain, direct prose. No filler. Flag anything that is unclear
or unsupported by the evidence — do not paper over gaps.

Deal/opportunity: {user_instruction}
""".strip(),
    },
]


def seed():
    sb = get_supabase()
    for skill in SKILLS:
        result = (
            sb.table("skills")
            .upsert(skill, on_conflict="name")
            .execute()
        )
        print(f"Seeded skill: {skill['name']}")
    print(f"\nDone. {len(SKILLS)} skills seeded.")


if __name__ == "__main__":
    seed()
```

Run it from your Hetzner VPS:

```bash
cd /opt/logios-brain
source venv/bin/activate
python3 scripts/seed_skills.py
```

Verify in Supabase Table Editor → skills: you should see all six rows.

---

## Adding new skills

Skills are just rows in the `skills` table. To add a new one, either:

**Via Supabase SQL Editor:**
```sql
INSERT INTO skills (name, description, prompt_template)
VALUES (
  'meeting_synthesis',
  'Convert meeting notes into decisions, actions, and risks',
  'Your prompt template here with {evidence_context} and {user_instruction} placeholders.'
);
```

**Via Python:**
```python
sb.table("skills").insert({
    "name": "meeting_synthesis",
    "description": "Convert meeting notes into decisions, actions, and risks",
    "prompt_template": "Your prompt template...",
}).execute()
```

**From your local AI via MCP:** Your AI can insert new skills directly by calling `remember` with the skill definition, or you can expose a `create_skill` tool by extending the MCP server.

---

## Querying evidence

The evidence table is the most valuable audit trail in the system. Example queries:

**What memories has the system cited most often?**
```sql
select
  m.content,
  m.source,
  count(e.id) as citation_count
from evidence e
join memories m on m.id = e.memory_id
group by m.id, m.content, m.source
order by citation_count desc
limit 20;
```

**What did the system know when it generated a specific output?**
```sql
select * from evidence_with_content
where generation_id = 'your-generation-uuid'
order by rank;
```

**Which memories have never been cited in any generation?**
```sql
select m.id, m.content, m.source, m.captured_at
from memories m
where m.id not in (
  select distinct memory_id from evidence where memory_id is not null
)
order by m.captured_at desc;
```

This last query is powerful — it shows you knowledge you have captured but never actually drawn on.

---

**Next: [Connecting AI Clients](08-connecting-clients.md)**