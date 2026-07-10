const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = 3000;
const DOCS_DIR = path.join(__dirname, '文档');

// ===== Text File Detection =====
const TEXT_EXTENSIONS = new Set([
    'txt', 'md', 'markdown', 'html', 'htm', 'xhtml',
    'json', 'xml', 'yaml', 'yml', 'toml',
    'ini', 'conf', 'cfg', 'log',
    'csv', 'tsv',
    'css', 'scss', 'less', 'sass',
    'js', 'mjs', 'cjs', 'ts', 'jsx', 'tsx',
    'py', 'rb', 'java', 'c', 'cpp', 'h', 'hpp', 'cs', 'go', 'rs', 'swift', 'kt', 'scala',
    'sh', 'bash', 'zsh', 'fish', 'ps1', 'bat', 'cmd',
    'sql', 'r', 'pl', 'lua', 'php', 'asp', 'jsp',
    'gradle', 'properties', 'env',
    'gitignore', 'dockerfile', 'editorconfig', 'dockerignore',
    'rst', 'tex', 'bib',
    'vue', 'svelte', 'astro',
    'svg', 'proto', 'graphql', 'gql',
    'Makefile', 'makefile', 'Dockerfile', 'README', 'LICENSE', 'CHANGELOG', 'CONTRIBUTING'
]);

const KNOWN_TEXT_NAMES = new Set([
    'makefile', 'dockerfile', 'gitignore', 'editorconfig', 'dockerignore',
    'readme', 'license', 'changelog', 'contributing', 'authors', 'todo',
    'gemfile', 'rakefile', 'procfile', 'vagrantfile', 'berksfile',
    'cmakelists.txt'
]);

function isTextFile(fileName) {
    const ext = fileName.split('.').pop().toLowerCase();
    if (ext === fileName || fileName.startsWith('.')) {
        return KNOWN_TEXT_NAMES.has(fileName.toLowerCase());
    }
    return TEXT_EXTENSIONS.has(ext);
}

// ===== Build File Tree =====
function buildTree(dirPath, relativePath) {
    const name = path.basename(dirPath);
    const stat = fs.statSync(dirPath);

    const node = {
        name: name,
        path: relativePath,
        type: stat.isDirectory() ? 'directory' : 'file',
        children: null,
        isBinary: false
    };

    if (stat.isDirectory()) {
        node.children = [];
        let entries;
        try {
            entries = fs.readdirSync(dirPath);
        } catch (e) {
            node.children = [{ name: '(读取失败)', path: relativePath + '/__error__', type: 'error', children: null, isBinary: false }];
            return node;
        }

        // Sort: directories first, then by name
        entries.sort((a, b) => {
            const aPath = path.join(dirPath, a);
            const bPath = path.join(dirPath, b);
            const aIsDir = fs.statSync(aPath).isDirectory();
            const bIsDir = fs.statSync(bPath).isDirectory();
            if (aIsDir !== bIsDir) return aIsDir ? -1 : 1;
            return a.localeCompare(b, 'zh-CN', { sensitivity: 'base' });
        });

        for (const entry of entries) {
            const childRelativePath = relativePath + '/' + entry;
            const childFullPath = path.join(dirPath, entry);
            node.children.push(buildTree(childFullPath, childRelativePath));
        }
    } else {
        node.isBinary = !isTextFile(name);
    }

    return node;
}

// ===== MIME Types =====
const MIME_MAP = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
};

// ===== HTTP Server =====
const server = http.createServer((req, res) => {
    const url = new URL(req.url, `http://localhost:${PORT}`);
    const pathname = url.pathname;
    const query = url.searchParams;

    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        res.writeHead(204);
        res.end();
        return;
    }

    // ===== API: GET /api/tree =====
    if (pathname === '/api/tree' && req.method === 'GET') {
        try {
            if (!fs.existsSync(DOCS_DIR)) {
                res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                res.end(JSON.stringify({
                    name: '文档',
                    path: '/文档',
                    type: 'directory',
                    children: [],
                    loaded: true,
                    isBinary: false
                }));
                return;
            }
            const tree = buildTree(DOCS_DIR, '/文档');
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify(tree));
        } catch (err) {
            res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: '读取目录失败: ' + err.message }));
        }
        return;
    }

    // ===== API: GET /api/read =====
    if (pathname === '/api/read' && req.method === 'GET') {
        const fileRelativePath = query.get('path');
        if (!fileRelativePath) {
            res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: '缺少 path 参数' }));
            return;
        }

        // Security: prevent path traversal
        // Remove the leading "/文档/" or "/文档" to get the relative path within DOCS_DIR
        let relativePath = fileRelativePath.replace(/^\/?文档/, '');
        // Normalize separators
        relativePath = relativePath.replace(/^[\\\/]+/, '').replace(/[\\\/]+/g, '\\');
        const fullPath = path.join(DOCS_DIR, relativePath);

        // Verify the resolved path is within DOCS_DIR
        const resolved = path.resolve(fullPath);
        if (!resolved.startsWith(path.resolve(DOCS_DIR))) {
            res.writeHead(403, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: '路径越权访问被拒绝' }));
            return;
        }

        try {
            if (!fs.existsSync(fullPath) || fs.statSync(fullPath).isDirectory()) {
                res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
                res.end(JSON.stringify({ error: '文件不存在或是一个目录' }));
                return;
            }
            const content = fs.readFileSync(fullPath, 'utf-8');
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ content: content }));
        } catch (err) {
            res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: '读取文件失败: ' + err.message }));
        }
        return;
    }

    // ===== API: POST /api/save =====
    if (pathname === '/api/save' && req.method === 'POST') {
        const fileRelativePath = query.get('path');
        if (!fileRelativePath) {
            res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: '缺少 path 参数' }));
            return;
        }

        // Security: prevent path traversal
        let relativePath = fileRelativePath.replace(/^\/?文档/, '');
        relativePath = relativePath.replace(/^[\\\/]+/, '').replace(/[\\\/]+/g, '\\');
        const fullPath = path.join(DOCS_DIR, relativePath);

        const resolved = path.resolve(fullPath);
        if (!resolved.startsWith(path.resolve(DOCS_DIR))) {
            res.writeHead(403, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: '路径越权访问被拒绝' }));
            return;
        }

        let body = '';
        req.on('data', chunk => body += chunk);
        req.on('end', () => {
            try {
                const data = JSON.parse(body);
                if (data.content === undefined) {
                    res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ error: '缺少 content 字段' }));
                    return;
                }

                // Ensure directory exists
                const dir = path.dirname(fullPath);
                if (!fs.existsSync(dir)) {
                    fs.mkdirSync(dir, { recursive: true });
                }

                fs.writeFileSync(fullPath, data.content, 'utf-8');
                res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                res.end(JSON.stringify({ success: true }));
            } catch (err) {
                res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
                res.end(JSON.stringify({ error: '保存文件失败: ' + err.message }));
            }
        });
        return;
    }

    // ===== Static Files =====
    let filePath;
    if (pathname === '/' || pathname === '/index.html') {
        filePath = path.join(__dirname, 'editor.html');
    } else {
        filePath = path.join(__dirname, pathname);
    }

    // Security: prevent path traversal for static files too
    if (!filePath.startsWith(__dirname)) {
        res.writeHead(403);
        res.end('Forbidden');
        return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_MAP[ext] || 'application/octet-stream';

    fs.readFile(filePath, (err, data) => {
        if (err) {
            res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
            res.end('404 Not Found');
            return;
        }
        res.writeHead(200, { 'Content-Type': contentType });
        res.end(data);
    });
});

server.listen(PORT, () => {
    console.log(`✅ 服务器已启动: http://localhost:${PORT}`);
    console.log(`📁 文档目录: ${DOCS_DIR}`);
    console.log('按 Ctrl+C 停止服务器');
});