#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vditor 文档编辑器 — 本地启动脚本
一键启动 HTTP 服务器，自动打开浏览器，直接浏览编辑「文档」文件夹。
"""

import http.server
import json
import os
import socket
import sys
import threading
import webbrowser
from urllib.parse import urlparse, parse_qs, unquote

PORT = 3000
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(ROOT_DIR, '文档')

# ===== Text File Detection =====
TEXT_EXTENSIONS = {
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
    'makefile', 'dockerfile', 'readme', 'license', 'changelog', 'contributing',
}

KNOWN_TEXT_NAMES = {
    'makefile', 'dockerfile', 'gitignore', 'editorconfig', 'dockerignore',
    'readme', 'license', 'changelog', 'contributing', 'authors', 'todo',
    'gemfile', 'rakefile', 'procfile', 'vagrantfile', 'berksfile',
    'cmakelists.txt',
}


def is_text_file(filename):
    """判断文件是否为文本文件（按扩展名和已知文件名）"""
    name_lower = filename.lower()
    if '.' not in filename or filename.startswith('.'):
        return name_lower in KNOWN_TEXT_NAMES
    ext = filename.rsplit('.', 1)[-1].lower()
    if not ext or ext == filename.lower():
        return name_lower in KNOWN_TEXT_NAMES
    return ext in TEXT_EXTENSIONS


# ===== MIME Types =====
MIME_MAP = {
    '.html': 'text/html; charset=utf-8',
    '.htm':  'text/html; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.js':   'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif':  'image/gif',
    '.svg':  'image/svg+xml',
    '.ico':  'image/x-icon',
    '.woff': 'font/woff',
    '.woff2':'font/woff2',
    '.ttf':  'font/ttf',
}


def get_mime(path):
    ext = os.path.splitext(path)[1].lower()
    return MIME_MAP.get(ext, 'application/octet-stream')


# ===== Build File Tree =====
def build_tree(dir_path, relative_path):
    """递归构建目录树 JSON 结构"""
    name = os.path.basename(dir_path)
    if os.path.isdir(dir_path):
        node = {
            'name': name,
            'path': relative_path,
            'type': 'directory',
            'children': [],
            'isBinary': False,
        }
        try:
            entries = os.listdir(dir_path)
        except OSError:
            node['children'] = [{
                'name': '(读取失败)',
                'path': relative_path + '/__error__',
                'type': 'error',
                'children': None,
                'isBinary': False,
            }]
            return node

        # 排序：目录在前，然后按名称
        def sort_key(e):
            full = os.path.join(dir_path, e)
            is_dir = os.path.isdir(full)
            return (0 if is_dir else 1, e.lower())

        entries.sort(key=sort_key)

        for entry in entries:
            child_relative = relative_path + '/' + entry
            child_full = os.path.join(dir_path, entry)
            node['children'].append(build_tree(child_full, child_relative))
    else:
        node = {
            'name': name,
            'path': relative_path,
            'type': 'file',
            'children': None,
            'isBinary': not is_text_file(name),
        }
    return node


# ===== Path Security =====
def safe_resolve(relative_path):
    """安全解析文档目录内的相对路径，防止目录穿越"""
    # 去掉 /文档 前缀
    cleaned = relative_path.replace('\\', '/')
    prefix = '/文档/'
    if cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix):]
    elif cleaned.startswith('/文档'):
        cleaned = cleaned[len('/文档'):]
    cleaned = cleaned.lstrip('/')

    full = os.path.normpath(os.path.join(DOCS_DIR, cleaned))
    docs_real = os.path.realpath(DOCS_DIR)
    full_real = os.path.realpath(full)
    if not full_real.startswith(docs_real + os.sep) and full_real != docs_real:
        return None
    return full


# ===== JSON Response Helper =====
def send_json(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', len(body))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(body)


# ===== Request Handler =====
class Handler(http.server.BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        pathname = parsed.path
        query = parse_qs(parsed.query)

        # ── GET /api/tree ──
        if pathname == '/api/tree':
            if not os.path.isdir(DOCS_DIR):
                send_json(self, {
                    'name': '文档',
                    'path': '/文档',
                    'type': 'directory',
                    'children': [],
                    'isBinary': False,
                })
                return
            tree = build_tree(DOCS_DIR, '/文档')
            send_json(self, tree)
            return

        # ── GET /api/read?path=... ──
        if pathname == '/api/read':
            file_path = query.get('path', [None])[0]
            if not file_path:
                send_json(self, {'error': '缺少 path 参数'}, 400)
                return
            file_path = unquote(file_path)
            full = safe_resolve(file_path)
            if full is None:
                send_json(self, {'error': '路径越权访问被拒绝'}, 403)
                return
            if not os.path.isfile(full):
                send_json(self, {'error': '文件不存在或是一个目录'}, 404)
                return
            try:
                with open(full, 'r', encoding='utf-8') as f:
                    content = f.read()
                send_json(self, {'content': content})
            except UnicodeDecodeError:
                send_json(self, {'error': '无法以文本方式读取此文件（可能是二进制文件）'}, 400)
            except OSError as e:
                send_json(self, {'error': f'读取文件失败: {e}'}, 500)
            return

        # ── Static File Serving ──
        if pathname == '/' or pathname == '/index.html':
            file_path = os.path.join(ROOT_DIR, 'editor.html')
        else:
            # Remove leading slash and join
            rel = pathname.lstrip('/')
            file_path = os.path.normpath(os.path.join(ROOT_DIR, rel))
            # Security: must be inside ROOT_DIR
            if not os.path.realpath(file_path).startswith(os.path.realpath(ROOT_DIR) + os.sep) \
               and os.path.realpath(file_path) != os.path.realpath(ROOT_DIR):
                self.send_error(403, 'Forbidden')
                return

        if not os.path.isfile(file_path):
            self.send_error(404, 'Not Found')
            return

        mime = get_mime(file_path)
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', len(data))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(500, 'Internal Server Error')

    def do_POST(self):
        parsed = urlparse(self.path)
        pathname = parsed.path
        query = parse_qs(parsed.query)

        # ── POST /api/save?path=... ──
        if pathname == '/api/save':
            file_path = query.get('path', [None])[0]
            if not file_path:
                send_json(self, {'error': '缺少 path 参数'}, 400)
                return
            file_path = unquote(file_path)
            full = safe_resolve(file_path)
            if full is None:
                send_json(self, {'error': '路径越权访问被拒绝'}, 403)
                return

            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')

            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                send_json(self, {'error': '无效的 JSON 请求体'}, 400)
                return

            if 'content' not in data:
                send_json(self, {'error': '缺少 content 字段'}, 400)
                return

            try:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, 'w', encoding='utf-8') as f:
                    f.write(data['content'])
                send_json(self, {'success': True})
            except OSError as e:
                send_json(self, {'error': f'保存文件失败: {e}'}, 500)
            return

        # ── POST /api/mkdir?path=... ──
        if pathname == '/api/mkdir':
            dir_path = query.get('path', [None])[0]
            if not dir_path:
                send_json(self, {'error': '缺少 path 参数'}, 400)
                return
            dir_path = unquote(dir_path)
            full = safe_resolve(dir_path)
            if full is None:
                send_json(self, {'error': '路径越权访问被拒绝'}, 403)
                return
            try:
                os.makedirs(full, exist_ok=True)
                send_json(self, {'success': True})
            except OSError as e:
                send_json(self, {'error': f'创建文件夹失败: {e}'}, 500)
            return

        # ── POST /api/create?path=... ──
        if pathname == '/api/create':
            file_path = query.get('path', [None])[0]
            if not file_path:
                send_json(self, {'error': '缺少 path 参数'}, 400)
                return
            file_path = unquote(file_path)
            full = safe_resolve(file_path)
            if full is None:
                send_json(self, {'error': '路径越权访问被拒绝'}, 403)
                return
            if os.path.exists(full):
                send_json(self, {'error': '文件已存在'}, 409)
                return
            try:
                parent = os.path.dirname(full)
                os.makedirs(parent, exist_ok=True)
                with open(full, 'w', encoding='utf-8') as f:
                    f.write('')
                send_json(self, {'success': True})
            except OSError as e:
                send_json(self, {'error': f'创建文件失败: {e}'}, 500)
            return

        # ── POST /api/rename?path=...&newName=... ──
        if pathname == '/api/rename':
            file_path = query.get('path', [None])[0]
            new_name = query.get('newName', [None])[0]
            if not file_path or not new_name:
                send_json(self, {'error': '缺少 path 或 newName 参数'}, 400)
                return
            file_path = unquote(file_path)
            new_name = unquote(new_name)
            full = safe_resolve(file_path)
            if full is None:
                send_json(self, {'error': '路径越权访问被拒绝'}, 403)
                return
            if not os.path.exists(full):
                send_json(self, {'error': '文件或文件夹不存在'}, 404)
                return
            # Prevent path traversal in newName
            if '/' in new_name or '\\' in new_name:
                send_json(self, {'error': '新名称不能包含路径分隔符'}, 400)
                return
            new_full = os.path.join(os.path.dirname(full), new_name)
            if not os.path.realpath(new_full).startswith(os.path.realpath(DOCS_DIR) + os.sep) \
               and os.path.realpath(new_full) != os.path.realpath(DOCS_DIR):
                send_json(self, {'error': '路径越权访问被拒绝'}, 403)
                return
            try:
                os.rename(full, new_full)
                send_json(self, {'success': True})
            except OSError as e:
                send_json(self, {'error': f'重命名失败: {e}'}, 500)
            return

        # ── POST /api/delete?path=... ──
        if pathname == '/api/delete':
            target_path = query.get('path', [None])[0]
            if not target_path:
                send_json(self, {'error': '缺少 path 参数'}, 400)
                return
            target_path = unquote(target_path)
            full = safe_resolve(target_path)
            if full is None or full == os.path.realpath(DOCS_DIR):
                send_json(self, {'error': '路径越权访问被拒绝'}, 403)
                return
            if not os.path.exists(full):
                send_json(self, {'error': '文件或文件夹不存在'}, 404)
                return
            try:
                if os.path.isdir(full):
                    import shutil
                    shutil.rmtree(full)
                else:
                    os.remove(full)
                send_json(self, {'success': True})
            except OSError as e:
                send_json(self, {'error': f'删除失败: {e}'}, 500)
            return

        # Unknown POST endpoint
        self.send_error(404, 'Not Found')

    def log_message(self, format, *args):
        print(f'  {self.command} {self.path} -> {args[1]}')

# ===== Entry Point =====
if __name__ == '__main__':
    # 修复 Windows 终端 GBK 编码下 emoji 打印问题
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass

    os.chdir(ROOT_DIR)
    server = http.server.HTTPServer(('127.0.0.1', PORT), Handler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    print()
    print(f'  [OK] 服务器已启动: http://localhost:{PORT}', flush=True)
    print(f'  [DOC] 文档目录: {DOCS_DIR}', flush=True)
    print(f'  [>>] 按 Ctrl+C 停止服务器', flush=True)
    print(flush=True)

    # 在后台线程打开浏览器，避免阻塞服务器启动
    def open_browser():
        try:
            webbrowser.open(f'http://localhost:{PORT}')
        except Exception:
            pass
    threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  [BYE] 服务器已停止')
        server.server_close()
        sys.exit(0)
