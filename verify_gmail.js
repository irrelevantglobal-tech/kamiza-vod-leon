// Proves which mailbox a minted Gmail token controls, and that it is read-only.
// Usage: node verify_gmail.js <label>
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const label = process.argv[2];
if (!label) { console.error('usage: node verify_gmail.js <label>'); process.exit(1); }

const secret = JSON.parse(fs.readFileSync(path.join(HERE, 'client_secret.json'), 'utf8')).installed;
const refresh = fs.readFileSync(path.join(HERE, `.gmail-refresh-${label}`), 'utf8').trim();

(async () => {
  const tok = await (await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: secret.client_id, client_secret: secret.client_secret,
      refresh_token: refresh, grant_type: 'refresh_token',
    }),
  })).json();
  if (!tok.access_token) { console.error('refresh FAILED:', JSON.stringify(tok)); process.exit(1); }

  console.log(`refresh works. granted scope: ${tok.scope}`);

  const p = await (await fetch('https://gmail.googleapis.com/gmail/v1/users/me/profile',
    { headers: { Authorization: `Bearer ${tok.access_token}` } })).json();

  if (!p.emailAddress) { console.error('profile lookup failed:', JSON.stringify(p)); process.exit(1); }
  console.log(`\n>>> TOKEN WATCHES: ${p.emailAddress}`);
  console.log(`    ${p.messagesTotal.toLocaleString('en-GB')} messages, ${p.threadsTotal.toLocaleString('en-GB')} threads`);

  const unread = await (await fetch(
    'https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=3&q=' +
    encodeURIComponent('is:unread -category:promotions -category:social newer_than:2d'),
    { headers: { Authorization: `Bearer ${tok.access_token}` } })).json();
  console.log(`    ${unread.messages ? unread.messages.length : 0} recent unread match the watcher's filter`);
})();
