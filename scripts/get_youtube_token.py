#!/usr/bin/env python3
"""
One-time YouTube OAuth2 token generator.
Run this ONCE on your local machine to get a refresh token,
then add it as a GitHub secret called YOUTUBE_REFRESH_TOKEN.

Usage:
  pip install google-auth-oauthlib
  python scripts/get_youtube_token.py
"""

import json
import os

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Installing google-auth-oauthlib...")
    os.system(f"{sys.executable} -m pip install google-auth-oauthlib")
    from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def find_credentials_file():
    """Look for the downloaded OAuth JSON file in common locations."""
    search_dirs = [
        Path.cwd(),
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path(__file__).parent,
    ]
    for d in search_dirs:
        for f in d.glob("client_secret_*.json"):
            return f
    return None


def main():
    print("=" * 60)
    print("MarketPhase — YouTube OAuth Setup")
    print("=" * 60)

    creds_file = find_credentials_file()
    if not creds_file:
        print("\nERROR: Could not find your client_secret_*.json file.")
        print("Place the downloaded OAuth credentials JSON file in:")
        print(f"  {Path.cwd()}")
        sys.exit(1)

    print(f"\nUsing credentials: {creds_file.name}")
    print("\nA browser window will open. Sign in with the Google account")
    print("that owns your YouTube channel and click Allow.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n" + "=" * 60)
    print("SUCCESS! Add these as GitHub repository secrets:")
    print("=" * 60)
    print(f"\nSecret name:  YOUTUBE_REFRESH_TOKEN")
    print(f"Secret value: {creds.refresh_token}")
    print(f"\nSecret name:  YOUTUBE_CLIENT_ID")
    print(f"Secret value: {creds.client_id}")
    print(f"\nSecret name:  YOUTUBE_CLIENT_SECRET")
    print(f"Secret value: {creds.client_secret}")
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
