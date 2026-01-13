# Google Cloud Setup for Voice Services

This guide explains how to set up Google Cloud credentials for Clavr's voice features (Speech-to-Text and Text-to-Speech).

## Prerequisites

- A Google account
- Access to Google Cloud Console

## Step-by-Step Setup

### 1. Create or Select a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top
3. Click **"New Project"** or select an existing project
4. Enter a project name (e.g., "Clavr Voice Services")
5. Click **"Create"**

### 2. Enable Required APIs

1. In the Google Cloud Console, go to **"APIs & Services"** > **"Library"**
2. Search for and enable:
   - **Cloud Speech-to-Text API**
   - **Cloud Text-to-Speech API**

### 3. Create a Service Account

1. Go to **"IAM & Admin"** > **"Service Accounts"**
2. Click **"Create Service Account"**
3. Fill in:
   - **Service account name**: `clavr-voice-service` (or your preferred name)
   - **Service account ID**: Auto-generated (or customize)
   - **Description**: "Service account for Clavr voice transcription and synthesis"
4. Click **"Create and Continue"**

### 4. Grant Required Permissions

1. In the **"Grant this service account access to project"** section, add these roles:
   - **Cloud Speech Client**
   - **Cloud Text-to-Speech API User**
2. Click **"Continue"**
3. Click **"Done"** (skip optional step)

### 5. Generate and Download JSON Key

1. Find your newly created service account in the list
2. Click on it to open details
3. Go to the **"Keys"** tab
4. Click **"Add Key"** > **"Create new key"**
5. Select **"JSON"** as the key type
6. Click **"Create"**
7. The JSON file will automatically download to your computer

**⚠️ Important**: Keep this JSON file secure! It contains credentials that grant access to your Google Cloud project.

### 6. Place the JSON File

1. Move the downloaded JSON file to a secure location in your Clavr project:
   ```bash
   # Example: Move to credentials directory
   mv ~/Downloads/clavr-voice-service-*.json /Users/maniko/Documents/clavr/credentials/
   ```

2. Make sure the file has appropriate permissions:
   ```bash
   chmod 600 /Users/maniko/Documents/clavr/credentials/*.json
   ```

### 7. Set Environment Variable

**Option A: Set in your shell (temporary)**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/Users/maniko/Documents/clavr/credentials/clavr-voice-service-abc123.json"
```

**Option B: Add to your shell profile (permanent)**
```bash
# Add to ~/.zshrc (or ~/.bashrc for bash)
echo 'export GOOGLE_APPLICATION_CREDENTIALS="/Users/maniko/Documents/clavr/credentials/clavr-voice-service-abc123.json"' >> ~/.zshrc
source ~/.zshrc
```

**Option C: Use a `.env` file** (if your project supports it)
```bash
# Create or edit .env file
echo "GOOGLE_APPLICATION_CREDENTIALS=/Users/maniko/Documents/clavr/credentials/clavr-voice-service-abc123.json" >> .env
```

### 8. Verify Setup

Restart your server and check the logs. You should see:
```
[OK] Google Cloud Speech client initialized with service account credentials
[OK] Google Cloud TTS client initialized with service account credentials
```

## Alternative: Using Default Credentials

If you're running on Google Cloud (Compute Engine, Cloud Run, etc.) or have run `gcloud auth application-default login`, you can use default credentials without setting `GOOGLE_APPLICATION_CREDENTIALS`.

## Troubleshooting

### Error: "Failed to initialize Google Speech client"
- Check that the JSON file path is correct
- Verify the file exists and is readable
- Ensure the service account has the correct permissions

### Error: "Permission denied"
- Check file permissions: `chmod 600 credentials/*.json`
- Verify the service account has the required IAM roles

### Error: "API not enabled"
- Go to Google Cloud Console > APIs & Services > Library
- Enable "Cloud Speech-to-Text API" and "Cloud Text-to-Speech API"

### Error: "Invalid credentials"
- Verify the JSON file is not corrupted
- Check that the service account hasn't been deleted
- Regenerate the key if needed

## Security Best Practices

1. **Never commit the JSON file to git** - Add it to `.gitignore`:
   ```
   credentials/*.json
   *.json
   ```

2. **Use environment variables** - Don't hardcode paths in your code

3. **Rotate keys regularly** - Generate new keys periodically and revoke old ones

4. **Limit permissions** - Only grant the minimum required roles

5. **Use separate service accounts** - Create different accounts for different environments (dev, staging, prod)

## Cost Considerations

- Google Cloud Speech-to-Text: Pay per audio minute transcribed
- Google Cloud Text-to-Speech: Pay per character synthesized
- Check [Google Cloud Pricing](https://cloud.google.com/pricing) for current rates
- Free tier may be available for limited usage

## Next Steps

After setting up credentials:
1. Restart your Clavr server
2. Test voice transcription in the frontend
3. Monitor usage in Google Cloud Console > Billing

