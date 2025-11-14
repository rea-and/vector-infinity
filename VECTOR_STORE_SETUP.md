# OpenAI Vector Store Setup Guide

This guide explains how to use OpenAI's Vector Store API with Vector Infinity to handle large amounts of context data efficiently.

## Overview

Instead of returning large amounts of text directly (which hits token limits), we use OpenAI's Vector Store API. This allows ChatGPT to:
- Store large amounts of data (thousands of emails)
- Automatically search and retrieve relevant context
- Avoid token limit issues
- Work more efficiently with large datasets

## Prerequisites

1. **OpenAI API Key**: You need an OpenAI API key with access to the Assistants API
2. **Set in `.env` file**:
   ```
   OPENAI_API_KEY=sk-your-api-key-here
   ```

## Setup Steps

### 1. Install Dependencies

The setup script should have already installed the `openai` package. If not:
```bash
source venv/bin/activate
pip install openai>=1.12.0
```

### 2. Import Your Data

1. Go to the web UI: `https://your-domain.com`
2. Navigate to the "Run Imports" tab
3. Click "Run Import" for the `gmail_personal` plugin
4. Wait for the import to complete

### 3. Sync to Vector Store

After importing data, sync it to OpenAI's Vector Store:

1. In the "Run Imports" tab, find your plugin card
2. Click the **"Sync to Vector Store"** button
3. Wait for the sync to complete (this may take a few minutes for large datasets)
4. You'll see a message with the **Vector Store ID** - **copy this ID!**

### 4. Configure ChatGPT Custom GPT

1. Go to [ChatGPT Custom GPTs](https://chat.openai.com/gpts)
2. Create a new GPT or edit an existing one
3. In the GPT configuration:
   - Go to **"Knowledge"** section
   - Under **"Vector Store"**, click **"Add Vector Store"**
   - Paste the **Vector Store ID** you copied earlier
   - Save the GPT

### 5. Use Your GPT

Now when you chat with your Custom GPT, it will automatically:
- Search the vector store for relevant emails
- Include relevant context in responses
- Handle large amounts of data efficiently

## How It Works

1. **Import**: Data is imported from Gmail and stored in the local SQLite database
2. **Sync**: Data is formatted and uploaded to OpenAI's Vector Store
3. **Search**: ChatGPT automatically searches the vector store when you ask questions
4. **Context**: Relevant emails are included in the conversation context

## Managing Vector Stores

### View Vector Store Info

Click the **"Vector Store Info"** button in the web UI to see:
- Store ID
- Store name
- Creation date
- File counts

### Re-sync Data

If you import new emails, you can re-sync to update the vector store:
1. Run a new import
2. Click "Sync to Vector Store" again
3. The vector store will be updated with new data

## Troubleshooting

### "Vector Store service not available"

- Make sure `OPENAI_API_KEY` is set in your `.env` file
- Restart the Flask app after adding the API key

### Sync fails

- Check that your OpenAI API key has access to the Assistants API
- Check the logs for detailed error messages
- Make sure you have imported data first (run an import before syncing)

### Vector Store ID not working in ChatGPT

- Make sure you copied the full Store ID
- Verify the store exists by clicking "Vector Store Info"
- The store ID should start with `vs_`

## Benefits

- **No Token Limits**: Vector stores can hold millions of tokens
- **Automatic Search**: ChatGPT finds relevant emails automatically
- **Efficient**: Only relevant context is retrieved, not everything
- **Scalable**: Can handle thousands of emails without issues

