# TickTick Plugin Setup Guide

This guide will help you set up the TickTick plugin to import your tasks (both completed and open) into Vector Infinity.

## Prerequisites

- A TickTick account
- Access to the TickTick Developer Portal

## Step 1: Register Your Application

1. Visit the [TickTick Developer Portal](https://developer.ticktick.com/)
2. Log in with your TickTick credentials
3. Click on "Manage Apps" or navigate to the app management section
4. Click "Create New App" or "Register App"
5. Fill in the application details:
   - **App Name**: Vector Infinity (or any name you prefer)
   - **Description**: Optional description
   - **OAuth Redirect URL**: `https://your-domain.com/api/plugins/ticktick/auth/callback`
     - Replace `your-domain.com` with your actual domain
     - For local development: `http://localhost:5000/api/plugins/ticktick/auth/callback`
6. After creating the app, you'll receive:
   - **Client ID**: A unique identifier for your app
   - **Client Secret**: A secret key for authentication (keep this secure!)

## Step 2: Configure the Plugin

1. Open the plugin configuration file:
   ```bash
   plugins/ticktick/config.json
   ```

2. Add your OAuth credentials:
   ```json
   {
     "nice_name": "TickTick",
     "client_id": "YOUR_CLIENT_ID_HERE",
     "client_secret": "YOUR_CLIENT_SECRET_HERE"
   }
   ```

3. Replace `YOUR_CLIENT_ID_HERE` and `YOUR_CLIENT_SECRET_HERE` with the values from Step 1.

## Step 3: Authenticate (First Run)

1. Start the Vector Infinity application
2. Navigate to the **Plugins** section in the web UI
3. Find the **TickTick** plugin card
4. Click the **Authenticate** button
5. You'll be redirected to TickTick's authorization page
6. Log in with your TickTick credentials
7. Review the permissions requested (read access to tasks)
8. Click **Authorize** or **Allow**
9. You'll be redirected back to Vector Infinity
10. The authentication should complete automatically

## Step 4: Import Tasks

1. After successful authentication, the **Authenticate** button will show a checkmark
2. Click the **Run Import** button
3. The plugin will fetch all your tasks (both completed and open)
4. Progress will be shown in real-time
5. Once complete, you'll see the number of tasks imported

## What Gets Imported

The plugin imports the following information for each task:

- **Task Title**: The name of the task
- **Status**: Whether the task is "Open" or "Completed"
- **Description**: The task content/notes
- **Project**: The project/list the task belongs to
- **Due Date**: When the task is due (if set)
- **Start Date**: When the task starts (if set)
- **Priority**: Task priority (Low, Medium, High)
- **Tags**: Any tags associated with the task
- **Timestamps**: Created and modified dates

## Troubleshooting

### Authentication Fails

- **Check Redirect URI**: Ensure the redirect URI in your TickTick app settings matches exactly:
  - Production: `https://your-domain.com/api/plugins/ticktick/auth/callback`
  - Development: `http://localhost:5000/api/plugins/ticktick/auth/callback`
- **Verify Credentials**: Double-check that `client_id` and `client_secret` in `config.json` are correct
- **Check HTTPS**: TickTick requires HTTPS for production. Make sure your domain has SSL certificates set up

### No Tasks Imported

- **Check Authentication**: Ensure you've successfully authenticated
- **Verify Permissions**: Make sure you authorized the app to read your tasks
- **Check Logs**: Look at the application logs for any error messages
- **Test Connection**: The plugin should show "Authenticated" status if the connection is working

### Token Expired

- If your access token expires, the plugin will automatically try to refresh it
- If refresh fails, you may need to re-authenticate by clicking the **Authenticate** button again

## API Limitations

- TickTick API has rate limits. The plugin respects these limits automatically
- Large numbers of tasks may take some time to import
- The plugin fetches all tasks (both completed and open) in a single import

## Security Notes

- **Never commit** `token.json` or `config.json` with real credentials to version control
- Keep your `client_secret` secure and private
- The `token.json` file contains sensitive authentication tokens - ensure proper file permissions

## Support

If you encounter issues:

1. Check the application logs for detailed error messages
2. Verify your TickTick app settings in the Developer Portal
3. Ensure your redirect URI matches exactly (including protocol and port)
4. Try re-authenticating if tokens seem invalid

For more information about the TickTick API, visit the [TickTick Developer Documentation](https://developer.ticktick.com/).

