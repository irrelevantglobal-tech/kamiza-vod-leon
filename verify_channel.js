// Proves which YouTube channel the minted refresh token actually controls.
// A token that works is not the same as a token pointing at the right channel -
// with a Brand Account it is very easy to authorise the personal account by
// mistake and not find out until VODs appear on the wrong channel.
// Reads secrets from disk, prints only channel identity.

const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const secret = JSON.parse(fs.readFileSync(path.join(HERE, 'client_secret.json'), 'utf8')).installed;
const refresh = fs.readFileSync(path.join(HERE, '.yt-refresh-token'), 'utf8').trim();

(async () => {
  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: secret.client_id,
      client_secret: secret.client_secret,
      refresh_token: refresh,
      grant_type: 'refresh_token',
    }),
  });
  const tok = await res.json();
  if (!tok.access_token) {
    console.error('refresh FAILED:', JSON.stringify(tok));
    console.error('If this says invalid_grant, the consent screen was still on Testing when minted.');
    process.exit(1);
  }
  console.log(`refresh works: access token issued, expires in ${tok.expires_in}s`);
  console.log(`granted scope: ${tok.scope}`);

  const ch = await fetch('https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true', {
    headers: { Authorization: `Bearer ${tok.access_token}` },
  });
  const body = await ch.json();
  if (!ch.ok) {
    console.log(`\nchannel lookup returned ${ch.status}: ${body.error && body.error.message}`);
    console.log('The youtube.upload scope alone often cannot read channel details.');
    console.log('That is expected and does not mean the token is wrong - but it does mean');
    console.log('the target channel is only provable by doing a real upload.');
    return;
  }
  for (const c of body.items || []) {
    console.log(`\n>>> TOKEN CONTROLS: "${c.snippet.title}"  (channel id ${c.id})`);
    console.log(`    subs ${c.statistics.subscriberCount} · videos ${c.statistics.videoCount} · views ${c.statistics.viewCount}`);
  }
})();
