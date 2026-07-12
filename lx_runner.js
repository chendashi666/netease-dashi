// LX Music runtime mock for running the music source script
const https = require('https');
const http = require('http');
const url = require('url');

// Mock globalThis.lx
globalThis.lx = {
    version: '2.10.0',
    request: function(requestUrl, options, callback) {
        const parsed = new URL(requestUrl);
        const mod = parsed.protocol === 'https:' ? https : http;
        const reqOptions = {
            hostname: parsed.hostname,
            port: parsed.port,
            path: parsed.pathname + parsed.search,
            method: options.method || 'GET',
            headers: options.headers || {},
        };
        const req = mod.request(reqOptions, (res) => {
            let body = '';
            res.on('data', (chunk) => body += chunk);
            res.on('end', () => {
                callback(null, { body, statusCode: res.statusCode, headers: res.headers });
            });
        });
        req.on('error', (err) => callback(err, null));
        if (options.body) req.write(options.body);
        req.end();
    },
    send: function(event, data) {},
    EVENT_NAMES: { request: 'request' },
};

// Load the music source script
const fs = require('fs');
const scriptPath = process.argv[2];
const action = process.argv[3];
const query = process.argv[4];

try {
    const sourceScript = fs.readFileSync(scriptPath, 'utf-8');
    eval(sourceScript);
    console.log('Script loaded successfully');
} catch (e) {
    console.error('Failed to load script:', e.message);
    process.exit(1);
}