const express = require('express');
const path = require('path');
const fs = require('fs');
const cors = require('cors');

const app = express();
const PORT = 3000;

// ⚠️ 改成你的实际目录（使用正斜杠）
const NOTES_DIR = 'D:/文档/github/Hello_World';

// 确保目录存在
if (!fs.existsSync(NOTES_DIR)) {
    fs.mkdirSync(NOTES_DIR, { recursive: true });
}

app.use(cors());
app.use(express.json({ limit: '50mb' })); // 提升限制以支持大图上传
app.use(express.static('public'));
// 将 assets 目录静态暴露，确保前端能正常预览图片
app.use('/assets', express.static(path.join(NOTES_DIR, 'assets')));

// ========== 安全路径函数 ==========
function safePath(relativePath) {
    if (!relativePath) return null;
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
        let fullPath = path.normalize(path.join(NOTES_DIR, cleaned));
        const relative = path.relative(NOTES_DIR, fullPath);
        if (relative.startsWith('..') || path.isAbsolute(relative)) {
            console.warn(`非法路径: ${relativePath} -> ${fullPath}`);
            return null;
        }
        return fullPath;
    } catch (err) {
        console.error(`路径解析错误: ${relativePath}`, err);
        return null;
    }
}

// ========== 递归获取目录树 ==========
function getDirectoryTree(dirPath, relativePath = '') {
    const items = [];
    try {
        const entries = fs.readdirSync(dirPath, { withFileTypes: true });
        for (const entry of entries) {
            if (entry.name.startsWith('.') || entry.name === 'assets') continue; // 过滤隐藏文件夹和资源文件夹
            const fullPath = path.join(dirPath, entry.name);
            const relPath = relativePath ? `${relativePath}/${entry.name}` : entry.name;
            if (entry.isDirectory()) {
                items.push({
                    type: 'folder',
                    name: entry.name,
                    path: relPath,
                    children: getDirectoryTree(fullPath, relPath)
                });
            } else {
                const ext = path.extname(entry.name).toLowerCase();
                items.push({
                    type: 'file',
                    name: entry.name,
                    path: relPath,
                    ext: ext,
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

// ========== API 路由 ==========
app.get('/api/tree', (req, res) => {
    try {
        const tree = getDirectoryTree(NOTES_DIR);
        res.json({ tree, rootPath: NOTES_DIR });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.get('/api/file', (req, res) => {
    const filePath = req.query.path;
    if (!filePath) return res.status(400).json({ error: '缺少 path 参数' });
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
    if (!filePath) return res.status(400).json({ error: '缺少 path 参数' });
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

// 新增：图片/附件 Base64 异步上传路由
app.post('/api/upload', (req, res) => {
    try {
        const { filename, base64Data } = req.body;
        if (!filename || !base64Data) return res.status(400).json({ error: '上传数据不完整' });

        const assetsDir = path.join(NOTES_DIR, 'assets');
        if (!fs.existsSync(assetsDir)) {
            fs.mkdirSync(assetsDir, { recursive: true });
        }

        // 清理 base64 头部声明
        const pureBase64 = base64Data.replace(/^data:image\/\w+;base64,/, "");
        const safeFileName = `${Date.now()}_${filename.replace(/\s+/g, '_')}`;
        const destPath = path.join(assetsDir, safeFileName);

        fs.writeFileSync(destPath, pureBase64, 'base64');
        
        // 返回相对路径供 Markdown 引用
        res.json({ success: true, url: `assets/${safeFileName}` });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.delete('/api/item', (req, res) => {
    const itemPath = req.query.path;
    if (!itemPath) return res.status(400).json({ error: '缺少 path 参数' });
    const fullPath = safePath(itemPath);
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
    if (!oldPath || !newName) return res.status(400).json({ error: '缺少参数' });
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
    const folderPath = req.query.path;
    if (!folderPath) return res.status(400).json({ error: '缺少 path 参数' });
    const fullPath = safePath(folderPath);
    if (!fullPath) return res.status(403).json({ error: '非法路径' });
    try {
        fs.mkdirSync(fullPath, { recursive: true });
        res.json({ success: true, path: folderPath });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.listen(PORT, () => {
    console.log(`Server running at http://localhost:${PORT}`);
    console.log(`Root directory: ${NOTES_DIR}`);
});