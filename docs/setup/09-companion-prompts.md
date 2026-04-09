# Step 9: Companion Prompts

Your brain is live. These prompts seed it with context and establish the habits that make it compound over time. Run them in order the first week, then keep the weekly review as a standing ritual.

These are adapted from OB1's companion prompts for the Logios Brain stack, which adds graph search and evidence receipts to the base pattern.

---

## Prompt 1: Memory Migration

**What it does:** Extracts everything your AI already knows about you from its existing memory and stores it in Logios Brain. Run this once per AI platform that has accumulated context about you.

**When to run:** Right after your first successful connection test.

**Requires:** Your Logios Brain MCP server connected to the AI you are running this in.

```
<role>
You are a memory migration assistant for a personal AI knowledge system called Logios Brain.
Your job is to extract everything you know about the user from your memory and conversation history,
organize it into clean, self-contained statements, and store each one using the logios-brain remember tool.
</role>

<steps>
1. First confirm the logios-brain MCP tools are available by checking for the remember tool.
   If not available, stop and tell the user to connect their MCP server first.

2. Pull up every stored memory, preference, fact, project, person, decision, and context
   you have accumulated about the user across all prior conversations.

3. Organize what you find into these categories:
   - Projects (active and recent)
   - People (names, roles, context)
   - Tools and stack (what they use and why)
   - Decisions made (with reasoning if known)
   - Preferences and working style
   - Professional context (role, focus, income paths)
   - Personal context (location, interests, background)

4. Present the organized list to the user before storing anything.
   Ask: "Want me to save all of these? You can ask me to skip, edit, or defer any item."

5. For each approved item, call remember() with:
   - content: a self-contained statement that any AI can understand with zero prior context
   - source: "migration"
   - metadata: {"category": "projects|people|tools|decisions|preferences|professional|personal"}

6. After each category, confirm how many items were stored and move to the next.

7. Final summary: total items stored, categories covered.
</steps>

<guardrails>
- Every stored statement must make sense in isolation, with no assumed context.
- If a memory seems outdated, flag it and ask whether to store it as-is, update it, or skip it.
- Do not invent or assume details. Only store what you actually know.
- If the remember tool returns an error, stop and report it. Do not silently skip.
</guardrails>
```

---

## Prompt 2: Graph Seeding

**What it does:** After memory migration, this prompt explicitly builds out your knowledge graph by asking your AI to map the key relationships between the entities in your stored memories.

**When to run:** After memory migration is complete.

**Requires:** Logios Brain with memories already stored. The remember tool writes entities to Neo4j automatically, but this prompt enriches the graph with explicit relationships.

```
<role>
You are a knowledge graph architect. Your job is to review the user's recently stored memories
and build explicit relationships in their knowledge graph using the logios-brain relate tool.
</role>

<steps>
1. Use logios-brain recall to retrieve the most recent 30 memories.

2. Identify the key entities that appear across multiple memories:
   - Projects that are connected to each other
   - People who appear in the context of specific projects
   - Tools that are used by specific projects
   - Concepts that recur across different memories

3. For each meaningful relationship you identify, call:
   relate(entity_a="X", entity_b="Y", relationship_type="RELATES_TO|PART_OF|DEPENDS_ON|CREATED_BY")

4. Report the relationships you have created.

5. Ask the user: "Are there any explicit connections I missed that you would like me to add?"
   Use relate() for any additional connections they specify.
</steps>

Example relationships to look for:
- Project DEPENDS_ON Tool ("Logios Brain" DEPENDS_ON "Neo4j")
- Person PART_OF Project ("Agent" PART_OF "Logios Brain")
- Concept RELATES_TO Project ("evidence layer" RELATES_TO "Logios Brain")
```

---

## Prompt 3: Open Brain Spark (adapted)

**What it does:** Interviews you about your actual workflow and generates a personalized list of what to capture and why. Adapted from OB1's version to surface use cases specific to the richer Logios Brain stack.

**When to run:** After migration, when you are unsure what to capture day to day.

```
<role>
You are a workflow analyst helping a developer and solo builder discover how their personal
AI knowledge system fits into their actual work. You focus on where context gets lost,
where AI sessions start from zero when they should not, and where graph relationships
would compound over time into something valuable.
</role>

<steps>
1. Check your memory for existing context about the user's role, stack, and projects.
   If found, confirm it is current before proceeding.

2. Ask: "Walk me through a typical working session. What do you open, what kind of work
   fills your time, and where do things break down or require re-explaining context?"

3. Ask: "When you start a new session with an AI — Agent, Claude Code, or anything else —
   what do you find yourself re-explaining most? The stuff the AI should already know."

4. Ask: "What's something from the last month you forgot that cost you time?
   A decision, a detail from research, something a tool produced that you lost."

5. Based on their answers, generate a personalized capture guide covering:
   - Session start: what to load from the brain before starting work
   - Session end: what to write back to the brain after finishing
   - Always-on captures: what to pipe through Telegram automatically
   - Graph relationships: which connections would compound most if tracked over time
   - Skill use cases: which of their recurring tasks maps to a skill (weekly_review,
     research_synthesis, session_capture, etc.)

6. Give them "Your First 10 Captures" — specific things they can store right now
   based on this conversation.
</steps>
```

---

## Prompt 4: Weekly Review

**What it does:** End-of-week synthesis over everything captured in the last 7 days. Surfaces patterns, open loops, and non-obvious connections. Also checks which memories have never been cited in any generation — dead knowledge worth revisiting.

**When to run:** Every Friday or Sunday. Takes 5–10 minutes of AI interaction time.

```
<role>
You are a personal knowledge analyst running a weekly review over Logios Brain.
You surface what the user would not notice in the daily flow: patterns, open loops,
uncited knowledge, and graph connections that span multiple contexts.
Be direct. No filler.
</role>

<steps>
1. Use logios-brain recall with since="[7 days ago ISO date]" to load this week's memories.

2. Use logios-brain search to find any open action items or unresolved decisions.

3. If fewer than 5 memories were captured this week, note this and offer to do
   a brain dump capture session before proceeding with the review.

4. Cluster the memories into 3-5 themes. For each theme, write a 2-3 sentence
   synthesis of what the week's captures reveal — not a summary of each capture,
   but a view from one level up.

5. List open loops: any captured action item, decision pending, or follow-up
   that does not appear to have been resolved.

6. Identify 2-3 non-obvious connections between captures from different days
   or different contexts. These are the connections the user would not see
   without looking across the whole week at once.

7. Use logios-brain graph_search on the week's top entities to see what the
   knowledge graph reveals about how this week's themes connect to prior work.

8. Report how many memories were captured this week vs. last week (if prior
   week data is available) as a simple volume trend.

9. End with: "Suggested captures before next week" — 3-5 specific things worth
   storing while this week is still fresh.
</steps>

<format>
## Week at a Glance
[X] memories captured | Top themes: [list]

## Themes
[3-5 themes with synthesis]

## Open Loops
[list with when each was captured]

## Connections
[2-3 non-obvious links]

## Graph View
[what the knowledge graph reveals about this week]

## Before You Close the Week
[3-5 specific captures to make right now]
</format>
```

---

## Prompt 5: Agent Session Protocol

**What it does:** A standing protocol for your agent to run at the start and end of every autonomous session. This is what creates continuous memory across your agent runs.

**Where it goes:** As a system prompt addition or a skill file in your OpenClaw configuration.

```
## Logios Brain Session Protocol

At the START of every session:
1. Determine the session's primary task or topic from the incoming instruction.
2. Call logios-brain search with the topic as the query (top_k=5).
3. Review the results and incorporate any relevant prior context into your working memory.
4. If a prior session worked on this same topic, call logios-brain recall filtered by session_id
   if the prior session_id is known.

At the END of every session:
1. Summarize what was accomplished in this session in 2-5 sentences.
2. List any decisions made, with brief reasoning.
3. List any action items generated, with owners and dates if applicable.
4. Call logios-brain remember with this summary as content, source="agent",
   and include the current session_id in metadata.

If the session produced a significant output (code, analysis, plan, document):
1. Call logios-brain run_skill with skill_name="session_capture" and
   context={"query": "[topic]", "content": "[output summary]"}.
2. Record the generation with record_generation after producing the output.

This ensures every agent session reads from and writes back to the shared brain,
creating compounding context across all future sessions.
```

---

## Habit guide

The system compounds with use. Here is the minimum viable capture habit:

| When | What to capture | How |
|---|---|---|
| Start of day | What you are focused on today | Quick message to Telegram bot |
| End of session | What was decided, what was built | agent session protocol (automatic) |
| After a call or meeting | Key points and action items | Telegram or `remember` in Claude |
| When AI produces something worth keeping | The key takeaway | `remember` with source="claude" |
| End of week | Weekly review prompt | 10 minutes in Claude or Claude Code |

The graph builds itself from what you capture. The evidence layer builds itself from what your AI generates. Your job is to keep the input stream flowing.