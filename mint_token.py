#!/usr/bin/env python3
"""
ONE-TIME local helper. Mints the YouTube refresh token for the VOD archive.

Differs from the old Forge version in one important way: it writes the token
to a FILE instead of printing it to the terminal. The old one printed it to
stdout, which would drop a permanent upload key to the channel straight into
a chat transcript. Secrets go to disk, never to a screen.

Run from this folder:
    py -m pip install google-auth-oauthlib
    py mint_token.py

A browser window opens. Pick the Google account that owns the channel you want
the VODs on. If the channel is a BRAND ACCOUNT (many streaming channels are), you will get
a second chooser listing the brand channels - pick the brand channel there, not
the personal account. Getting that wrong sends every VOD to the wrong channel
and you will not notice for weeks.

You will also see "Google hasn't verified this app". That is expected for an app
you wrote yourself. Advanced -> Go to <app> (unsafe).
"""

import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit("missing dependency. run:  py -m pip install google-auth-oauthlib")

# upload   = put the VOD on the channel.
# readonly = PROVE which channel the token controls, and read subs/views for stats.
#            Without it, channels.list 403s and the only way to find out where
#            VODs land is to upload one and look.
# youtube  = create and add to the "VoD Archive" playlist. upload alone cannot
#            touch playlists at all - playlists.insert returns 403 with it.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
]
HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = os.path.join(HERE, "client_secret.json")
OUT = os.path.join(HERE, ".yt-refresh-token")


def main():
    if not os.path.exists(SECRET):
        sys.exit(f"client_secret.json not found in {HERE}")

    flow = InstalledAppFlow.from_client_secrets_file(SECRET, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        sys.exit("no refresh token returned. The consent screen is probably still "
                 "on 'Testing', or consent was not re-prompted.")

    with open(OUT, "w", encoding="ascii") as fh:
        fh.write(creds.refresh_token)

    # Deliberately reports only the shape, never the value.
    print(f"OK: refresh token written to {os.path.basename(OUT)} "
          f"({len(creds.refresh_token)} chars). Not printed here on purpose.")
    print("Next: it goes into the GitHub repo secret YT_REFRESH_TOKEN, nowhere else.")


if __name__ == "__main__":
    main()
