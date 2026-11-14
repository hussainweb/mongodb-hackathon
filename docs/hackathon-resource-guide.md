# Agents in Context Toronto — Official Resource Guide Summary

- **Source:** [Google Doc — Agents in Context: A MongoDB Hackathon Resource Guide](https://docs.google.com/document/d/1rrsNKU3guyvExg_oBPpfOrZF9Ypr5xPLFQ9yYJ2C60o/edit?tab=t.0)
- **Date & Venue:** November 14 · The Quay, Toronto

---

## Hackathon Day Schedule (Nov 14)

| Time (ET) | Milestone |
| :--- | :--- |
| **9:00 AM** | Doors open & team formation |
| **10:45 AM** | Hacking begins |
| **5:00 PM** | Submissions due |
| **5:15 PM – 6:45 PM** | First round judging |
| **7:00 PM** | Final round judging (Top 6 teams present) |
| **8:15 PM** | Winners announced |

---

## Problem Statements (Official Tracks)

Every project must be built in **one** of the three statements below, using **MongoDB Atlas** as your data, memory, and state layer.

### Statement One: Agents You Can Audit

> An agent that can't explain what it did, and who allowed it, never leaves the sandbox. Build an agent using MongoDB Atlas as the identity, policy and audit layer (collections, schema validation, change streams) that takes real actions across systems, where every action is tied to an identity, checked against policy before it runs, and recorded so a reviewer can reconstruct it afterward.

- How do you decide what an agent may do and enforce it before the action, not after?
- How do you record what the agent did, why, and under whose authority?
- How do you stop or roll back an agent mid-run?

### Statement Two: Memory You Can Govern

> What an agent remembers is data someone has to answer for. Build an agent using MongoDB Atlas and Vector Search to persist and retrieve memory, so that memory changes what it does on the next run, with rules for who can read each memory, how long it lives, and how it gets corrected or forgotten.

- How do you keep one client's or team's memory from leaking into another's?
- How does the agent fix or drop a memory that turns out wrong or expired?
- How do you prove a memory changed the agent's behavior and didn't just fill the prompt?

### Statement Three: Finish the Job

> Real work spans many systems and takes hours, and the systems won't hold still. Build an agent that completes a long multi-step task across several systems, using MongoDB Atlas to persist verified task state and Vector Search to retrieve relevant past experience, so it survives crashes and system changes and knows what actually happened.

- How does it tell an action that took effect from one that was only sent?
- How does it resume after a crash without replaying its whole history?
- How does it adapt when a system's layout, fields or workflow changes underneath it?

---

## Requirements & Submission Checklist

- **Finalist requirement (MongoDB Atlas Sandbox):** Must create project + cluster through the hackathon Atlas Sandbox email link and build the project on it.
- **No prior projects:** All work must be original.
- **Demo access:** Repository must be **public** and your **demo link** must be accessible.
- **Team size:** Up to 4 members.
- **Attendance:** All demos are live and in-person.
- **Cerebral Valley Platform Submission (due 5:00 PM):**
  - Link to public GitHub repository
  - 1-minute demo video showing the code & functionality built today (verify **both video & audio playback**)
  - Concise project description detailing what you built
  - Double-check that **all team members** are added to the submission

---

## Prizes

| Placement | MongoDB | LangSmith | ElevenLabs |
| :--- | :--- | :--- | :--- |
| **1st Place** | $7,000 USD | $3,000 Credits | 3 months Pro Tier |
| **2nd Place** | $5,000 USD | $2,000 Credits | — |
| **3rd Place** | $3,000 USD | $1,000 Credits | — |
| **Best Project Built with ElevenLabs** | — | — | 3 months Scale Tier |

---

## MongoDB Resources

### Recommended Starting Point
1. [MongoDB Agent Skills](https://www.mongodb.com/docs/agent-skills/) — Coding-assistant best practices for connecting, data modeling, querying, and search.
2. [MongoDB MCP Server](https://www.mongodb.com/docs/mcp-server/get-started/) — Direct live database inspection, querying, counts, and Atlas resource management.
3. [Natural Language to MongoDB Queries](https://www.mongodb.com/docs/manual/natural-language-to-mongodb/) — Prompting guidance for task, data structure, and output format.

### Developer Tools, Data, Search, State & Starter Code
- **Developer Tools:** Atlas Managed MCP Server; Frontier Marketplace Connectors (ChatGPT/Codex, Claude, Gemini, Grok Build, Devin, Cursor).
- **Data & Search:** [Sample Movie Dataset](https://www.mongodb.com/docs/atlas/sample-data/sample-mflix) · [Data Modeling in MongoDB](https://www.mongodb.com/docs/manual/data-modeling/#data-modeling) · [Vector Search](https://www.mongodb.com/products/platform/atlas-vector-search) · [Atlas Search](https://www.mongodb.com/docs/atlas/atlas-search/) · [Automated Embeddings](https://www.mongodb.com/company/blog/product-release-announcements/unlocking-ai-search-introducing-automated-embedding-in-mongodb-vector-search) · [Embedding and Reranking API](https://www.mongodb.com/docs/api/doc/atlas-embedding-and-reranking-api/)
- **Memory & Agents:** [Agent with Memory & Function Calling](https://www.mongodb.com/developer/products/atlas/interactive-rag-mongodb-atlas-function-calling-api/) · [Adding Memory (Python)](https://www.mongodb.com/developer/products/atlas/advanced-rag-langchain-mongodb/) · [Adding Memory (JavaScript)](https://www.mongodb.com/developer/products/atlas/add-memory-to-javascript-rag-application-mongodb-langchain/)
- **State:** [Build an AI Agent with LangGraph and MongoDB Atlas](https://www.mongodb.com/docs/atlas/ai-integrations/langgraph/build-agents/) · [State & Persistence: The Problem of Agent Reliability](https://www.mongodb.com/company/blog/technical/state-persistence-the-problem-of-agent-reliability)
- **Context:** [Build AI Agents with MongoDB](https://www.mongodb.com/docs/atlas/ai-agents/) · [GraphRAG with MongoDB and LangChain](https://www.mongodb.com/docs/atlas/ai-integrations/langchain/graph-rag/)
- **Starter Code & Post-Event:** [GenAI Showcase](https://github.com/mongodb-developer/GenAI-Showcase/tree/main) · [MongoDB and Python Quickstart](https://github.com/mongodb-developer/mongodb-atlas-python-quickstart/blob/main/quickstart-1-getting-started-atlas-python.ipynb) · [MERN Starter Application](https://github.com/mongodb-developer/mern-stack-example) · [MongoDB for Startups](https://www.mongodb.com/startups)

---

## Partner Resources & Credits

*(Most partner credits require being registered and checked in on the Cerebral Valley Platform.)*

### ElevenLabs — 1 Month Creator Plan Free (131k Credits)
- **Redeem:** Join [ElevenLabs Discord](https://discord.com/invite/VnBvbbcdEC) -> `#coupon-codes` -> **Start Redemption** -> select this event and submit the email registered on Cerebral Valley to receive a coupon code.
- **Post-event:** Fill out the hacker feedback form linked in the [ElevenLabs Hacker Guide](https://docs.google.com/document/d/1mCh5MtOzBw0aJpurQVUmIVFfPMAHW3MjNemE-LNiMto/edit?tab=t.0).
- **Tutorial:** [Redemption video tutorial](https://youtu.be/S143_JtCtV8)

### LangChain / LangSmith — $50 Credits + Deployments Access
- **Redeem:** Submit the [Airtable credit form](https://airtable.com/appzjKToipPcn2dKI/pagTsO0Ld3edczsrV/form) within 10 days of the hackathon (enter the hackathon name as the event). Add a card to LangSmith to display credits (it won't be charged).
- **Docs:** [LangChain hacker resources](https://app.notion.com/p/Hackathon-Resources-from-LangChain-34f808527b1780c8a82bd0b8f0c322a2) · [LangGraph docs](https://docs.langchain.com/oss/python/langgraph/overview) · [Deep Agents quickstart](https://docs.langchain.com/oss/python/deepagents/quickstart)

### Voyage AI — 200 Million Free Tokens
- **Setup:** [Create a Voyage AI Account](https://dashboard.voyageai.com/) -> [Generate API Key](https://dashboard.voyageai.com/organization/api-keys) -> [Add a Payment Method](https://dashboard.voyageai.com/organization/billing) to unlock Tier 1 [rate limits](https://docs.voyageai.com/docs/rate-limits) (no charge within the 200M free token allowance).
- **Python Client & Docs:** `pip install voyageai` (or `uv add voyageai`) · [API Key & Python Client Setup](https://docs.voyageai.com/docs/api-key-and-installation) · [Quickstart Tutorial](https://docs.voyageai.com/docs/quickstart-tutorial) · [Pricing & Free Credits](https://docs.voyageai.com/docs/pricing) · [Usage Dashboard](https://dashboard.voyageai.com/organization/usage)
- **Top-ups / Support:** Ask the event host or on-site Voyage AI team if approaching the 200M token limit.
