// Tiny static file server for local preview (Node, no deps).
const http = require('http');
const fs = require('fs');
const path = require('path');
const ROOT = '/Users/hurleywhite/Developer/arcticblue-event-tracker/public';
const TYPES = { '.html':'text/html', '.js':'text/javascript', '.json':'application/json', '.ics':'text/calendar', '.png':'image/png', '.svg':'image/svg+xml', '.css':'text/css' };
http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/index.html';
  const file = path.join(ROOT, p);
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end('no'); }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
}).listen(8765, '127.0.0.1', () => console.log('serving', ROOT, 'on 8765'));
