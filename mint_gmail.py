#!/usr/bin/env python3
"""
ONE-TIME. Mints a READ-ONLY Gmail token so the bot can post "you have mail"
lines into Discord. It can read; it can never send, delete or modify anything.

Run from this folder:
    py mint_gmail.py <label>

<label> is just a filename tag, e.g.  py mint_gmail.py me
                                      py mint_gmail.py cohost

The browser opens. SIGN IN AS THE MAILBOX YOU WANT WATCHED - not whichever
Google account happens to be logged in already. That is the mistake to avoid:
you would end up watching the wrong inbox and not notice for days.

Writes .gmail-refresh-<label> and prints only its length, never the token.
"""

import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit("missing dependency. run:  py -m pip install google-auth-oauthlib")

# Read-only. Cannot send, cannot delete, cannot mark as read.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = os.path.join(HERE, "client_secret.json")


def main():
    label = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if not label:
        sys.exit("usage: py mint_gmail.py <label>   e.g.  py mint_gmail.py me")

    if not os.path.exists(SECRET):
        sys.exit(f"client_secret.json not found in {HERE}")

    out = os.path.join(HERE, f".gmail-refresh-{label}")

    flow = InstalledAppFlow.from_client_secrets_file(SECRET, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        sys.exit("no refresh token returned - consent was not re-prompted, or the "
                 "OAuth consent screen is still on 'Testing'.")

    with open(out, "w", encoding="ascii") as fh:
        fh.write(creds.refresh_token)

    print(f"\nOK: wrote {os.path.basename(out)} ({len(creds.refresh_token)} chars).")
    print("Not printed here on purpose. Tell Claude it worked.")


if __name__ == "__main__":
    main()
