# Semantic Search Setup Guide

This guide explains how to use semantic search with vector embeddings in Vector Infinity for Custom GPT Actions.

## Overview

Semantic search uses vector embeddings to find emails by meaning, not just keywords. This allows ChatGPT to find relevant emails even when they don't contain the exact words you're searching for.

**Example:** Searching for "vacation plans" will find emails about "trip to Italy", "holiday booking", "travel arrangements", etc.

## How It Works

1. **Import**: When you import data, embeddings are automatically generated for each email
2. **Storage**: Embeddings are stored in your local SQLite database
3. **Search**: When ChatGPT needs to search, it calls the semantic search endpoint
4. **Results**: The endpoint finds the most similar emails using cosine similarity

## Prerequisites

1. **OpenAI API Key**: Required for generating embeddings
2. **Set in `.env` file**:
   ```
   OPENAI_API_KEY=sk-your-api-key-here
   ```

## Setup Steps

### 1. Install Dependencies

The setup script should have already installed the required packages. If not:
```bash
source venv/bin/activate
pip install openai>=1.12.0 numpy>=1.24.0
```

### 2. Import Your Data

1. Go to the web UI: `https://your-domain.com`
2. Navigate to the "Run Imports" tab
3. Click "Run Import" for the `gmail_personal` plugin
4. Wait for the import to complete
   - **Embeddings are generated automatically during import**
   - You'll see progress: "Generating embeddings for X items..."

### 3. Configure ChatGPT Custom GPT

1. **Download the schema**: In the Vector Infinity web UI, click "Download Schema" for your plugin
   - Or manually get: `plugins/gmail_personal/custom_gpt_schema.json`

2. **Update the server URL**: Open the schema file and replace `https://vectorinfinity.com/` with your actual server URL

3. **Add as Action in ChatGPT**:
   - Go to [ChatGPT Custom GPTs](https://chat.openai.com/gpts)
   - Create a new GPT or edit an existing one
   - Go to "Configure" tab
   - Scroll to "Actions" section
   - Click "Create new action"
   - Click "Import from URL" or paste the JSON schema content
   - Paste the contents of `custom_gpt_schema.json`
   - Add authentication if needed (API key, bearer token, etc.)
   - Save the GPT

### 4. Use Your GPT

Now when you chat with your Custom GPT, it will automatically:
- Use the `semanticSearchGmailPersonal` action when you ask questions about emails
- Find semantically similar emails (by meaning, not just keywords)
- Include relevant context in responses

**Example queries:**
- "Find emails about my vacation" - will find emails about trips, holidays, travel, etc.
- "What did I discuss with John about the project?" - will find relevant project emails
- "Show me emails related to invoices" - will find billing, payment, receipt emails

## How Semantic Search Works

1. **Query Processing**: Your question is converted to an embedding vector
2. **Similarity Search**: The system compares this vector against all email embeddings
3. **Ranking**: Results are ranked by cosine similarity (0-1, higher is more similar)
4. **Top Results**: The top K most similar emails are returned

## Benefits

- **Semantic Understanding**: Finds emails by meaning, not just exact words
- **Full Control**: Your data stays in your database
- **No Quotas**: Uses your own embeddings, not OpenAI Vector Store quotas
- **Fast**: Embeddings are pre-computed during import
- **Scalable**: Can handle thousands of emails efficiently

## Troubleshooting

### "No items with embeddings found"

- Make sure you've run an import after setting `OPENAI_API_KEY`
- Check the import logs to see if embedding generation succeeded
- Re-run the import to generate embeddings

### Embedding generation fails

- Check that `OPENAI_API_KEY` is set correctly in `.env`
- Verify your API key has access to the embeddings API
- Check the logs for detailed error messages

### Search returns no results

- Make sure embeddings were generated (check import logs)
- Try a different query - semantic search works best with descriptive queries
- Check that you have emails imported for the plugin

## Technical Details

- **Embedding Model**: `text-embedding-3-small` (OpenAI)
- **Similarity Metric**: Cosine similarity
- **Storage**: Embeddings stored as BLOB in SQLite
- **Batch Processing**: Embeddings generated in batches during import for efficiency

## Comparison: Semantic Search vs OpenAI Vector Store

| Feature | Semantic Search (Actions) | OpenAI Vector Store |
|---------|---------------------------|---------------------|
| Data Control | Full control (your DB) | Managed by OpenAI |
| Quotas | Uses embedding API only | Vector Store quotas |
| Setup | Action in Custom GPT | Knowledge section |
| Search Type | Semantic (by meaning) | Semantic (by meaning) |
| Cost | Embedding generation | Vector Store storage |

Both approaches work well. Choose based on your needs:
- **Semantic Search (Actions)**: More control, no Vector Store quotas
- **OpenAI Vector Store**: Simpler setup, managed by OpenAI

