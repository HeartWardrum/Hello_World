import json
import os
import sys

# 导入原生拖拽和 UI 库
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    print("❌ 错误：未检测到 tkinterdnd2 库！")
    print("请在环境里运行: pip install tkinterdnd2")
    sys.exit(1)

def get_desktop_path():
    """获取当前系统桌面的绝对路径"""
    return os.path.join(os.path.expanduser("~"), "Desktop")

def has_selected_api(node):
    """🚀 核心修复逻辑：递归检查某个节点（或文件夹内部）是否包含至少一个被勾选的接口"""
    if node["type"] == "api":
        return node["var"].get()
    elif node["type"] == "folder":
        # 只要子项里有一个返回 True，该文件夹就判定为“有被选中的接口”
        return any(has_selected_api(child) for child in node["children"])
    return False

def generate_markdown_with_tree(structure, output_filename, collection_name):
    """根据带层级的结构生成支持文件夹分层的 Markdown"""
    desktop_dir = get_desktop_path()
    output_md_path = os.path.join(desktop_dir, output_filename)
    if not output_md_path.endswith('.md'):
        output_md_path += '.md'

    markdown_content = [f"# {collection_name}\n", "--- \n"]

    def write_node(node, level=2):
        """递归写入节点（支持无限层级文件夹）"""
        # 如果是文件夹
        if node["type"] == "folder":
            # 🚀 核心修复：如果这个文件夹里面没有任何一个接口被勾选，直接默默跳过，不写入标题
            if not has_selected_api(node):
                return
                
            hashes = "#" * level
            markdown_content.append(f"{hashes} 📁 {node['name']}\n")
            for child in node["children"]:
                write_node(child, level + 1)
        
        # 如果是接口且被勾选了
        elif node["type"] == "api" and node["var"].get():
            item = node["data"]
            name = item.get("name", "未命名接口")
            request = item.get("request", {})
            method = request.get("method", "GET")
            
            desc = request.get("description", item.get("description", ""))
            if isinstance(desc, dict):
                desc = desc.get("content", "")
            desc_text = desc if desc else "无"

            url_data = request.get("url", {})
            url = url_data.get("raw", "") if isinstance(url_data, dict) else str(url_data)
                
            hashes = "#" * level
            markdown_content.append(f"{hashes} 📄 {name}\n")
            markdown_content.append(f"* **接口功能**: {desc_text}")
            markdown_content.append(f"* **请求 URL**: `{url}`")
            markdown_content.append(f"* **请求方式**: `{method}`")
            
            body_data = request.get("body", {})
            body_mode = body_data.get("mode", "")
            
            if body_mode == "raw":
                raw_content = body_data.get("raw", "")
                markdown_content.append(f"* **数据格式**: `application/json` \n")
                markdown_content.append(f"{hashes}# 📥 请求参数 (Request Body)\n")
                markdown_content.append("```json")
                try:
                    parsed_body = json.loads(raw_content)
                    markdown_content.append(json.dumps(parsed_body, indent=4, ensure_ascii=False))
                except:
                    markdown_content.append(raw_content)
                markdown_content.append("```\n")
                
                try:
                    if isinstance(parsed_body, dict):
                        markdown_content.append(f"{hashes}# 📊 参数说明\n")
                        markdown_content.append("| 参数名 | 类型 | 是否必填 | 说明 |")
                        markdown_content.append("| :--- | :--- | :--- | :--- |")
                        for key, value in parsed_body.items():
                            type_name = type(value).__name__
                            type_map = {"str": "String", "int": "Integer", "list": "Array", "dict": "Object", "bool": "Boolean"}
                            type_name = type_map.get(type_name, type_name)
                            markdown_content.append(f"| `{key}` | {type_name} | 是/否 |  |")
                        markdown_content.append("\n")
                except:
                    pass
            else:
                markdown_content.append("* **数据格式**: 无 / 非 raw 格式\n")
                
            markdown_content.append(f"{hashes}# 📤 返回参数 (Response)\n")
            markdown_content.append("```json")
            markdown_content.append("{\n    \"code\": 200,\n    \"msg\": \"success\",\n    \"data\": {}\n}")
            markdown_content.append("```\n")
            markdown_content.append("---\n")

    for root_node in structure:
        write_node(root_node, level=2)

    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(markdown_content))
        
    return output_md_path

class PostmanConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Postman 接口高级导出工具")
        self.root.geometry("620x560")
        
        self.font_style = ("Microsoft YaHei", 10)
        self.tree_structure = []     
        self.collection_name = "API Documentation"
        self.is_bulk_updating = False 

        # 1. JSON文件路径区域
        tk.Label(root, text="第一步：拖入或选择 Postman JSON 文件:", font=self.font_style).pack(anchor="w", padx=20, pady=(15, 2))
        file_frame = tk.Frame(root)
        file_frame.pack(fill="x", padx=20)
        
        self.file_entry = tk.Entry(file_frame, font=self.font_style)
        self.file_entry.pack(side="left", fill="x", expand=True, ipady=3)
        
        self.file_entry.drop_target_register(DND_FILES)
        self.file_entry.dnd_bind('<<Drop>>', self.handle_drop)
        
        btn_browse = tk.Button(file_frame, text=" 浏览... ", font=self.font_style, command=self.browse_file)
        btn_browse.pack(side="right", padx=(10, 0))
        
        self.btn_parse = tk.Button(root, text="🔍 点击解析并分层渲染接口", font=self.font_style, bg="#2f54eb", fg="white", command=self.parse_json_file)
        self.btn_parse.pack(fill="x", padx=20, pady=10)

        # 2. 接口列表顶部控制区
        list_header_frame = tk.Frame(root)
        list_header_frame.pack(fill="x", padx=20, pady=(5, 2))
        
        self.list_label = tk.Label(list_header_frame, text="第二步：请选择接口 (支持按文件夹全选):", font=self.font_style)
        self.list_label.pack(side="left")
        
        self.global_var = tk.BooleanVar(value=True)
        self.cb_global = tk.Checkbutton(list_header_frame, text="全局全选/全不选", variable=self.global_var, font=("Microsoft YaHei", 9, "bold"), fg="#2f54eb", command=self.toggle_global_all)
        self.cb_global.pack(side="right")
        
        self.canvas_frame = tk.Frame(root, bd=1, relief="sunken")
        self.canvas_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        self.canvas = tk.Canvas(self.canvas_frame, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # 3. 输出文件名及转换按钮区域
        tk.Label(root, text="第三步：输出 Markdown 文件名:", font=self.font_style).pack(anchor="w", padx=20, pady=(10, 2))
        self.name_entry = tk.Entry(root, font=self.font_style)
        self.name_entry.pack(fill="x", padx=20, ipady=3)
        self.name_entry.insert(0, "API_Documentation")
        
        self.btn_convert = tk.Button(root, text="🚀 转化选中的接口并保存至桌面", font=("Microsoft YaHei", 11, "bold"), bg="#107c41", fg="white", command=self.start_conversion)
        self.btn_convert.pack(fill="x", padx=20, pady=(15, 15), ipady=5)

    def browse_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if file_path:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, os.path.normpath(file_path))
            self.parse_json_file()

    def handle_drop(self, event):
        path = event.data
        if path.startswith('{') and path.endswith('}'): path = path.strip('{}')
        if path.startswith('"') and path.endswith('"'): path = path.strip('"')
        path = os.path.normpath(path)
        self.file_entry.delete(0, tk.END)
        self.file_entry.insert(0, path)
        self.parse_json_file()

    def build_tree(self, item_list):
        nodes = []
        for item in item_list:
            if "request" in item: 
                nodes.append({
                    "type": "api",
                    "name": item.get("name", "未命名接口"),
                    "data": item,
                    "var": tk.BooleanVar(value=True) 
                })
            elif "item" in item: 
                nodes.append({
                    "type": "folder",
                    "name": item.get("name", "未命名文件夹"),
                    "children": self.build_tree(item["item"]),
                    "var": tk.BooleanVar(value=True) 
                })
        return nodes

    def parse_json_file(self):
        json_path = self.file_entry.get().strip().strip('"')
        if not json_path or not os.path.exists(json_path):
            messagebox.showwarning("提示", "请先选择或拖入合法的 Postman JSON 文件！")
            return
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.collection_name = data.get("info", {}).get("name", "API Documentation")
            self.tree_structure = self.build_tree(data.get("item", []))
            
            for widget in self.scrollable_frame.winfo_children():
                widget.destroy()

            if not self.tree_structure:
                messagebox.showinfo("提示", "未在该文件中检测到任何接口或文件夹。")
                return

            self.render_tree_ui(self.tree_structure, self.scrollable_frame, indent=0)
            self.global_var.set(True)
                
        except Exception as e:
            messagebox.showerror("错误", f"解析失败。原因:\n{str(e)}")

    def render_tree_ui(self, nodes, parent_frame, indent=0):
        for node in nodes:
            row_frame = tk.Frame(parent_frame)
            row_frame.pack(fill="x", anchor="w", padx=(indent * 20, 0), pady=2)

            if node["type"] == "folder":
                cb = tk.Checkbutton(
                    row_frame, 
                    text=f"📁 {node['name']}", 
                    variable=node["var"],
                    font=("Microsoft YaHei", 10, "bold"),
                    fg="#a8071a", 
                    command=lambda n=node: self.toggle_folder_all(n)
                )
                cb.pack(side="left")
                self.render_tree_ui(node["children"], parent_frame, indent + 1)

            elif node["type"] == "api":
                req = node["data"].get("request", {})
                method = req.get("method", "GET")
                display_text = f" [{method}]  {node['name']}"
                
                cb = tk.Checkbutton(
                    row_frame, 
                    text=display_text, 
                    variable=node["var"],
                    font=self.font_style,
                    command=self.update_ui_linkage
                )
                cb.pack(side="left")

    def toggle_folder_all(self, folder_node):
        if self.is_bulk_updating: return
        self.is_bulk_updating = True
        
        status = folder_node["var"].get()
        def set_status(node, val):
            node["var"].set(val)
            if node["type"] == "folder":
                for child in node["children"]:
                    set_status(child, val)
                    
        for child in folder_node["children"]:
            set_status(child, status)
            
        self.is_bulk_updating = False
        self.update_ui_linkage()

    def toggle_global_all(self):
        if self.is_bulk_updating: return
        self.is_bulk_updating = True
        
        status = self.global_var.get()
        def set_status_all(nodes, val):
            for node in nodes:
                node["var"].set(val)
                if node["type"] == "folder":
                    set_status_all(node["children"], val)
                    
        set_status_all(self.tree_structure, status)
        self.is_bulk_updating = False

    def update_ui_linkage(self):
        if self.is_bulk_updating: return
        
        def check_and_update(nodes):
            all_node_checked = True
            for node in nodes:
                if node["type"] == "folder":
                    child_status = check_and_update(node["children"])
                    node["var"].set(child_status)
                    if not child_status: all_node_checked = False
                elif node["type"] == "api":
                    if not node["var"].get(): all_node_checked = False
            return all_node_checked

        global_status = check_and_update(self.tree_structure)
        self.global_var.set(global_status)

    def count_selected(self, nodes):
        count = 0
        for node in nodes:
            if node["type"] == "api" and node["var"].get():
                count += 1
            elif node["type"] == "folder":
                count += self.count_selected(node["children"])
        return count

    def start_conversion(self):
        if not self.tree_structure:
            messagebox.showwarning("提示", "当前没有可转化的接口树，请先载入并解析 JSON 文件！")
            return
            
        out_name = self.name_entry.get().strip()
        if not out_name:
            messagebox.showwarning("提示", "请填写输出的文档名称！")
            return

        selected_count = self.count_selected(self.tree_structure)
        if selected_count == 0:
            messagebox.showwarning("提示", "您没有勾选任何接口，请至少勾选一个进行转化！")
            return

        try:
            saved_path = generate_markdown_with_tree(self.tree_structure, out_name, self.collection_name)
            messagebox.showinfo("成功", f"🎉 转化成功！\n已成功将 {selected_count} 个接口按层级保存至桌面:\n{os.path.basename(saved_path)}")
        except Exception as e:
            messagebox.showerror("错误", f"转化失败，原因:\n{str(e)}")

if __name__ == "__main__":
    window = TkinterDnD.Tk()
    app = PostmanConverterApp(window)
    window.mainloop()