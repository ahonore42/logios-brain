"""
scripts/seed_skills.py

Seeds the skills table with initial prompt templates.

Run once after schema setup is complete and the server is running:

    cd /opt/logios-brain
    source venv/bin/activate
    python3 scripts/seed_skills.py

Uses upsert on the skill name, so it is safe to re-run — existing
skills will not be overwritten unless you change their name.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from dotenv import load_dotenv

load_dotenv("/opt/logios-brain/.env")

from db.postgres import execute

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
You are a session capture assistant. Your job is to extract the permanent
knowledge from this working session and prepare it for storage.

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

Session focus: {user_instruction}
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

Deal or opportunity: {user_instruction}
""".strip(),
    },
]


def seed() -> None:
    seeded = 0
    skipped = 0

    for skill in SKILLS:
        existing = execute(
            "SELECT id FROM skills WHERE name = %s",
            (skill["name"],),
        )

        if existing:
            print(f"  skipped  {skill['name']} (already exists)")
            skipped += 1
            continue

        execute(
            """
            INSERT INTO skills (name, description, prompt_template)
            VALUES (%s, %s, %s)
            """,
            (skill["name"], skill["description"], skill["prompt_template"]),
            fetch=False,
        )
        print(f"  seeded   {skill['name']}")
        seeded += 1

    print(f"\nDone. {seeded} seeded, {skipped} already existed.")


if __name__ == "__main__":
    print("\nSeeding skills...\n")
    seed()
