# Step 1: Service Setup

Before writing any code or running any SQL, you need accounts and credentials across four services. This doc walks through every one of them in the order you will need them.

> **Keep a credential file open while you do this.** Call it `credentials.local` or similar, put it in your home directory (never in the repo), and add it to your global `.gitignore`. Several credentials cannot be retrieved after you leave the page.

Add this to `~/.gitignore` right now:
```
credentials.local
.env
*.env
```

---

## 1. Supabase

Supabase is your Postgres ledger — the system of record that every other store references by `memory_id`.

### Create the project

1. Go to [supabase.com](https://supabase.com) and sign up (GitHub login is fastest)
2. Click **New Project**
3. Set project name: `logios-brain` (or whatever you prefer)
4. Generate a strong database password — **save this immediately**, it cannot be retrieved later
5. Choose the region closest to your Hetzner VPS location
6. Click **Create new project** and wait 1–2 minutes

### Save these credentials

In your Supabase dashboard, go to **Settings → API Keys**:

```
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SERVICE_KEY=your_secret_key_here
SUPABASE_PROJECT_REF=your_project_ref
SUPABASE_DB_PASSWORD=the_password_you_set_above
```

The **Project ref** is the random string in your dashboard URL:
`supabase.com/dashboard/project/THIS_PART`

The **Service key** (also called secret key) is under the "Secret keys" section on the API Keys page. This is different from the publishable/anon key — you want the secret one.

> The anon key is for browser clients. The service key bypasses Row Level Security and is what your server uses. Never expose it publicly.

### Enable the vector extension

In the left sidebar: **Database → Extensions** → search "vector" → enable **pgvector**.

You need this on before running any schema migrations.

---

## 2. Neo4j AuraDB

Neo4j AuraDB Free gives you one graph instance, 200MB storage, and 200K nodes — plenty for a personal knowledge graph.

### Create the instance

1. Go to [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura) and sign up
2. Click **Create a free instance**
3. Name it `logios-brain`
4. Choose the region closest to your Hetzner VPS
5. **Download the credentials file immediately** when prompted — this is the only time you will see the generated password

### Save these credentials

```
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=the_password_from_the_downloaded_file
```

### Important: AuraDB Free pauses after inactivity

The free tier pauses instances after 3 days of no activity. You will need to log in and resume it if this happens. In production use this will not be an issue — your server pings it regularly. But be aware during initial setup if you take breaks between steps.

---

## 3. Qdrant Cloud

Qdrant Cloud Free gives you one cluster with 1GB RAM and 4GB disk. More than enough for a personal knowledge base with tens of thousands of embedded chunks.

### Create the cluster

1. Go to [cloud.qdrant.io](https://cloud.qdrant.io) and sign up
2. Click **Create cluster**
3. Select **Free tier**
4. Name it `logios-brain`
5. Choose the region closest to your Hetzner VPS
6. Wait for the cluster to provision (1–2 minutes)

### Save these credentials

Once provisioned, go to the cluster dashboard and click **API Keys → Create API Key**:

```
QDRANT_URL=https://YOUR_CLUSTER_ID.us-east4-0.gcp.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key
```

The URL format will match your cluster's region. Copy it exactly from the dashboard.

---

## 4. Gemini API

You need a Google AI Studio account to get a free Gemini API key for `gemini-embedding-001`.

### Get the key

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in with a Google account
3. Click **Get API key → Create API key**
4. Select an existing Google Cloud project or create a new one named `logios-brain`
5. Copy the key immediately

### Save the credential

```
GEMINI_API_KEY=AIza...your_key_here
```

### Free tier limits

The Gemini embedding free tier supports 10 million tokens per minute. At personal knowledge base ingestion volume this limit is essentially unlimited. If you ever hit it, the server will receive a 429 and should retry with exponential backoff — we will wire this into the server code.

### Privacy note

The free tier does log requests to improve Google's models. This is fine for non-sensitive personal knowledge base content. If you are embedding sensitive content (financial records, medical notes, etc.), either use the paid tier or switch to a self-hosted embedding model like `nomic-embed-text` via Ollama on your System76.

---

## 5. Hetzner VPS

You already have this. What you need from it:

```
HETZNER_IP=your.vps.ip.address
HETZNER_USER=your_ssh_username
```

### Check your available RAM

```bash
ssh your_user@your_vps_ip
free -h
```

The MCP server (FastAPI + dependencies) uses approximately 200–400MB RAM at idle. If your VPS is a CX11 (2GB RAM), you are fine. If it is smaller, consider upgrading to CX21 (~€4.90/month) before deploying.

### Ensure Python 3.11+ is available

```bash
python3 --version
```

If it is below 3.11:
```bash
sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip -y
```

---

## 6. Your `.env` file

Once you have all credentials, create this file on your Hetzner VPS at `/opt/logios-brain/.env`. You will create the directory when you deploy the server in step 3. For now, keep the values in your local `credentials.local`.

The final `.env` will look like this:

```env
# Supabase
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SERVICE_KEY=your_service_key

# Neo4j
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password

# Qdrant
QDRANT_URL=https://YOUR_CLUSTER_ID.region.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key

# Gemini
GEMINI_API_KEY=your_gemini_api_key

# MCP Server
MCP_ACCESS_KEY=generate_this_with_openssl_rand_hex_32
SERVER_PORT=8000
```

Generate your MCP access key now:
```bash
openssl rand -hex 32
```

Save the output as `MCP_ACCESS_KEY` in your credential file. This is what every AI client will use to authenticate to your server.

---

## Checkpoint

Before moving to schema setup, verify you have all of the following saved:

- [ ] `SUPABASE_URL`
- [ ] `SUPABASE_SERVICE_KEY`
- [ ] `SUPABASE_PROJECT_REF`
- [ ] `NEO4J_URI`
- [ ] `NEO4J_USERNAME`
- [ ] `NEO4J_PASSWORD`
- [ ] `QDRANT_URL`
- [ ] `QDRANT_API_KEY`
- [ ] `GEMINI_API_KEY`
- [ ] `MCP_ACCESS_KEY`
- [ ] `HETZNER_IP`

**Do not proceed to [Step 2: Schema](02-schema.md) until every item above is checked.**