# Fridge to Recipe

A Streamlit app that identifies ingredients in a fridge or pantry photo and suggests recipes that fit the user's dietary preferences.

## Features

- Analyze a JPG, PNG, or WebP photo with Gemini. The app tries `gemini-3.8-flash` first and can retry with other supported Gemini models.
- Review and edit detected ingredients before generating recipe ideas.
- Enter ingredients manually if photo analysis is unavailable.
- Share the latest recipe through a WhatsApp link.
- Fall back to a simple local recipe suggestion if Gemini recipe generation fails.

## Requirements

- Python and pip
- A Gemini Developer API key from [Google AI Studio](https://aistudio.google.com/apikey)
- Twilio credentials (required by the current app startup configuration)

## Run locally

From the project directory, create and activate a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml` and add your own credentials:

```toml
GEMINI_API_KEY = "your-gemini-api-key"
TWILIO_ACCOUNT_SID = "your-twilio-account-sid"
TWILIO_AUTH_TOKEN = "your-twilio-auth-token"
TWILIO_WHATSAPP_FROM = "whatsapp:+your-twilio-sender-number"

# Optional: a Twilio WhatsApp Content Template SID.
TWILIO_CONTENT_SID = "your-content-template-sid"
```

Run the app:

```powershell
streamlit run app.py
```

The app opens at `http://localhost:8501` by default.

## Deploy with Streamlit Community Cloud

1. Connect the GitHub repository to Streamlit Community Cloud.
2. Set the app entry point to `app.py` and the branch to `main`.
3. Add the secrets above in the app's **Settings → Secrets**. Use real credentials there; do not commit them to GitHub.
4. Deploy the app. Later pushes to `main` trigger a redeploy.

The local `.streamlit/secrets.toml` file is ignored by Git. Local secrets do not automatically transfer to Streamlit Community Cloud.