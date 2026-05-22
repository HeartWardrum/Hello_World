const express = require('express');
const path = require('path');
const fs = require('fs');
const cors = require('cors');

const app = express();
const PORT = 3000;

// ========== 动态配置管理 ==========
const CONFIG_FILE = path.join(__dirname, 'config.json');
let config = { currentRoot: '', favorites: [] };

// 启动时加载配置
if (fs.existsSync(CONFIG_FILE)) {
    try {
        config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    } catch (e) {
        console.error('读取配置文件失败，使用默认配置');
    }
}

function saveConfig() {
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2), 'utf-8');
}

app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.static('public'));

// ========== 动态资源路由 (替代原先静态挂载) ==========
app.use('/assets', (req, res) => {
    if (!config.currentRoot) return res.status(403).send('未配置根目录');
    
    // 从 req.path 直接获取去掉 /assets 后的剩余路径，天然支持中文和任意子目录
    const assetPath = path.normalize(path.join(config.currentRoot, 'assets', decodeURIComponent(req.path)));
    
    // 防止跳出 assets 目录的安全校验
    const relative = path.relative(path.join(config.currentRoot, 'assets'), assetPath);
    if (relative.startsWith('..') || path.isAbsolute(relative)) {
        return res.status(403).send('非法路径');
    }
    
    if (fs.existsSync(assetPath)) {
        res.sendFile(assetPath);
    } else {
        res.status(404).send('图片未找到');
    }
});

// ========== API：配置与主页管理 ==========
app.get('/api/config', (req, res) => {
    res.json(config);
});

app.post('/api/config/root', (req, res) => {
    const { targetPath } = req.body;
    if (!targetPath) return res.status(400).json({ error: '路径不能为空' });
    const normalizedPath = path.normalize(targetPath).replace(/\\/g, '/');
    
    if (!fs.existsSync(normalizedPath)) {
        try {
            fs.mkdirSync(normalizedPath, { recursive: true });
        } catch (e) {
            return res.status(400).json({ error: '路径不存在且无法创建' });
        }
    }
    
    config.currentRoot = normalizedPath;
    saveConfig();
    res.json({ success: true, root: config.currentRoot });
});

app.post('/api/config/favorite', (req, res) => {
    const { favPath, action } = req.body;
    const normalizedPath = path.normalize(favPath).replace(/\\/g, '/');
    
    if (action === 'add') {
        if (!config.favorites.includes(normalizedPath)) config.favorites.push(normalizedPath);
    } else if (action === 'remove') {
        config.favorites = config.favorites.filter(p => p !== normalizedPath);
    }
    
    saveConfig();
    res.json({ success: true, favorites: config.favorites });
});


// ========== 安全路径函数 ==========
function safePath(relativePath) {
    if (!relativePath || !config.currentRoot) return null;
    try {
        let decoded = decodeURIComponent(relativePath);
        decoded = decoded.replace(/\\/g, '/');
        const parts = decoded.split('/');
        const safeParts = [];
        for (const part of parts) {
            if (part === '..') return null;
            safeParts.push(part);
        }
        const cleaned = safeParts.join('/');
        let fullPath = path.normalize(path.join(config.currentRoot, cleaned));
        const relative = path.relative(config.currentRoot, fullPath);
        if (relative.startsWith('..') || path.isAbsolute(relative)) {
            return null;
        }
        return fullPath;
    } catch (err) {
        return null;
    }
}

// ========== 递归获取目录树 ==========
function getDirectoryTree(dirPath, relativePath = '') {
    const items = [];
    try {
        const entries = fs.readdirSync(dirPath, { withFileTypes: true });
        for (const entry of entries) {
            if (entry.name.startsWith('.') || entry.name === 'assets') continue; 
            const fullPath = path.join(dirPath, entry.name);
            const relPath = relativePath ? `${relativePath}/${entry.name}` : entry.name;
            if (entry.isDirectory()) {
                items.push({
                    type: 'folder', name: entry.name, path: relPath,
                    children: getDirectoryTree(fullPath, relPath)
                });
            } else {
                const ext = path.extname(entry.name).toLowerCase();
                items.push({
                    type: 'file', name: entry.name, path: relPath, ext: ext,
                    editable: ['.md', '.markdown', '.txt', '.mdx', '.json', '.js', '.css', '.html', '.py'].includes(ext)
                });
            }
        }
        items.sort((a, b) => {
            if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
            return a.name.localeCompare(b.name);
        });
    } catch (err) {
        console.error(`读取目录失败 ${dirPath}:`, err);
    }
    return items;
}

// ========== 业务路由 ==========
app.get('/api/tree', (req, res) => {
    if (!config.currentRoot) return res.status(400).json({ error: '未设置根目录' });
    try {
        const tree = getDirectoryTree(config.currentRoot);
        res.json({ tree, rootPath: config.currentRoot });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.get('/api/file', (req, res) => {
    const filePath = req.query.path;
    const fullPath = safePath(filePath);
    if (!fullPath) return res.status(403).json({ error: '非法路径' });
    if (!fs.existsSync(fullPath)) return res.status(404).json({ error: '文件不存在' });
    try {
        const content = fs.readFileSync(fullPath, 'utf-8');
        res.json({ content, path: filePath });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/file', (req, res) => {
    const filePath = req.query.path;
    const fullPath = safePath(filePath);
    if (!fullPath) return res.status(403).json({ error: '非法路径' });
    const dir = path.dirname(fullPath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    try {
        fs.writeFileSync(fullPath, req.body.content, 'utf-8');
        res.json({ success: true, path: filePath });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/upload', (req, res) => {
    try {
        if (!config.currentRoot) return res.status(400).json({ error: '未配置根目录' });
        const { filename, base64Data } = req.body;
        if (!filename || !base64Data) return res.status(400).json({ error: '上传数据不完整' });

        const assetsDir = path.join(config.currentRoot, 'assets');
        if (!fs.existsSync(assetsDir)) fs.mkdirSync(assetsDir, { recursive: true });

        const pureBase64 = base64Data.replace(/^data:image\/\w+;base64,/, "");
        const safeFileName = `${Date.now()}_${filename.replace(/\s+/g, '_')}`;
        const destPath = path.join(assetsDir, safeFileName);

        fs.writeFileSync(destPath, pureBase64, 'base64');
        res.json({ success: true, url: `assets/${safeFileName}` });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.delete('/api/item', (req, res) => {
    const fullPath = safePath(req.query.path);
    if (!fullPath) return res.status(403).json({ error: '非法路径' });
    try {
        const stat = fs.statSync(fullPath);
        if (stat.isDirectory()) fs.rmSync(fullPath, { recursive: true, force: true });
        else fs.unlinkSync(fullPath);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.put('/api/rename', (req, res) => {
    const oldPath = req.query.path;
    const { newName } = req.body;
    const oldFullPath = safePath(oldPath);
    if (!oldFullPath) return res.status(403).json({ error: '非法路径' });
    const newFullPath = path.join(path.dirname(oldFullPath), newName);
    try {
        fs.renameSync(oldFullPath, newFullPath);
        const parentDir = path.dirname(oldPath);
        const newRelativePath = parentDir === '.' ? newName : path.join(parentDir, newName);
        res.json({ success: true, newPath: newRelativePath.replace(/\\/g, '/') });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/folder', (req, res) => {
    const fullPath = safePath(req.query.path);
    if (!fullPath) return res.status(403).json({ error: '非法路径' });
    try {
        fs.mkdirSync(fullPath, { recursive: true });
        res.json({ success: true, path: req.query.path });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.listen(PORT, () => {
    console.log(`Server running at http://localhost:${PORT}`);
});