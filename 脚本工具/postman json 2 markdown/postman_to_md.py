import json
import os
import sys

# 🚀 导入真正的拖拽库
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError:
    print("❌ 错误：未检测到 tkinterdnd2 库！")
    print("请在环境里运行: pip install tkinterdnd2")
    sys.exit(1)

def get_desktop_path():
    """获取当前系统桌面的绝对路径"""
    return os.path.join(os.path.expanduser("~"), "Desktop")

def parse_postman_to_markdown(json_file_path, output_filename):
    """核心转换逻辑"""
    if not os.path.exists(json_file_path):
        raise FileNotFoundError(f"找不到输入的 JSON 文件：{json_file_path}")
        
    desktop_dir = get_desktop_path()
    output_md_path = os.path.join(desktop_dir, output_filename)
    if not output_md_path.endswith('.md'):
        output_md_path += '.md'

    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    collection_name = data.get("info", {}).get("name", "API Documentation")
    markdown_content = [f"# {collection_name}\n", "--- \n"]

    items = data.get("item", [])
    for index, item in enumerate(items, 1):
        name = item.get("name", "未命名接口")
        request = item.get("request", {})
        method = request.get("method", "GET")
        
        url_data = request.get("url", {})
        url = url_data.get("raw", "") if isinstance(url_data, dict) else str(url_data)
            
        markdown_content.append(f"## {index}. {name}\n")
        markdown_content.append(f"* **接口描述**: {name}")
        markdown_content.append(f"* **请求 URL**: `{url}`")
        markdown_content.append(f"* **请求方式**: `{method}`")
        
        body_data = request.get("body", {})
        body_mode = body_data.get("mode", "")
        
        if body_mode == "raw":
            raw_content = body_data.get("raw", "")
            markdown_content.append(f"* **数据格式**: `application/json` \n")
            markdown_content.append("### 📥 请求参数 (Request Body)\n")
            markdown_content.append("```json")
            try:
                parsed_body = json.loads(raw_content)
                markdown_content.append(json.dumps(parsed_body, indent=4, ensure_ascii=False))
            except:
                markdown_content.append(raw_content)
            markdown_content.append("```\n")
            
            try:
                if isinstance(parsed_body, dict):
                    markdown_content.append("### 📊 参数说明\n")
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
            
        markdown_content.append("### 📤 返回参数 (Response)\n")
        markdown_content.append("```json")
        markdown_content.append("{\n    \"code\": 200,\n    \"msg\": \"success\",\n    \"data\": {}\n}")
        markdown_content.append("```\n")
        markdown_content.append("---\n")

    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(markdown_content))
        
    return output_md_path

class PostmanConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Postman JSON 转 Markdown 工具 (支持原生拖拽)")
        self.root.geometry("520x280")
        self.root.resizable(False, False)
        
        font_style = ("Microsoft YaHei", 10)
        
        # 1. JSON文件路径组件
        tk.Label(root, text="JSON 文件路径 (👉 直接把 JSON 文件拖到下方输入框内):", font=font_style).pack(anchor="w", padx=20, pady=(20, 2))
        
        file_frame = tk.Frame(root)
        file_frame.pack(fill="x", padx=20)
        
        self.file_entry = tk.Entry(file_frame, font=font_style)
        self.file_entry.pack(side="left", fill="x", expand=True, ipady=3)
        
        # 🚀 核心改动：注册拖拽事件
        self.file_entry.drop_target_register(DND_FILES)
        self.file_entry.dnd_bind('<<Drop>>', self.handle_drop)
        
        btn_browse = tk.Button(file_frame, text=" 浏览... ", font=font_style, command=self.browse_file)
        btn_browse.pack(side="right", padx=(10, 0))
        
        # 2. 输出文件名组件
        tk.Label(root, text="输出 Markdown 文件名 (例如: 接口文档):", font=font_style).pack(anchor="w", padx=20, pady=(15, 2))
        self.name_entry = tk.Entry(root, font=font_style)
        self.name_entry.pack(fill="x", padx=20, ipady=3)
        self.name_entry.insert(0, "API_Documentation")
        
        # 3. 提示信息
        self.tips_label = tk.Label(root, text=f"💡 转换成功后，文件将自动生成到您的桌面", font=("Microsoft YaHei", 9), fg="gray")
        self.tips_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        # 4. 开始转换按钮
        self.btn_convert = tk.Button(root, text="🚀 开始转换并保存至桌面", font=("Microsoft YaHei", 11, "bold"), bg="#107c41", fg="white", command=self.start_conversion)
        self.btn_convert.pack(fill="x", padx=20, pady=(20, 0), ipady=5)

    def browse_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if file_path:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, os.path.normpath(file_path))
            
    def handle_drop(self, event):
        """处理文件拖入事件，并清洗 Windows 自带的特殊符号"""
        path = event.data
        # Windows 拖拽多个或带空格路径时，可能会用 {} 或 "" 包裹
        if path.startswith('{') and path.endswith('}'):
            path = path.strip('{}')
        if path.startswith('"') and path.endswith('"'):
            path = path.strip('"')
            
        path = os.path.normpath(path)
        
        self.file_entry.delete(0, tk.END)
        self.file_entry.insert(0, path)

    def start_conversion(self):
        json_path = self.file_entry.get().strip().strip('"')
        out_name = self.name_entry.get().strip()
        
        if not json_path:
            messagebox.showwarning("提示", "请先选择或拖入 Postman JSON 文件！")
            return
        if not out_name:
            messagebox.showwarning("提示", "请填写输出的文档名称！")
            return
            
        try:
            saved_path = parse_postman_to_markdown(json_path, out_name)
            messagebox.showinfo("成功", f"🎉 转换成功！\n文件已保存至桌面:\n{os.path.basename(saved_path)}")
        except Exception as e:
            messagebox.showerror("错误", f"转换失败，原因:\n{str(e)}")

if __name__ == "__main__":
    # 🚀 实例化支持拖拽的窗口，代替普通的 tk.Tk()
    window = TkinterDnD.Tk()
    app = PostmanConverterApp(window)
    window.mainloop()