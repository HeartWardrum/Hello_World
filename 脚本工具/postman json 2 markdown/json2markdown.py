import json

def postman_to_markdown(json_file_path, output_md_path):
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    md_lines = []
    
    # 文档标题
    collection_name = data.get('info', {}).get('name', 'API文档')
    md_lines.append(f'# {collection_name}\n')
    
    # 递归处理请求
    def process_items(items, level=2):
        for item in items:
            name = item.get('name', '未命名')
            md_lines.append(f"{'#' * level} {name}\n")
            
            # 如果有请求详情
            request = item.get('request')
            if request:
                method = request.get('method', 'GET')
                url = request.get('url', {}).get('raw', '')
                md_lines.append(f"- **Method**: `{method}`\n")
                md_lines.append(f"- **URL**: `{url}`\n")
                
                # 请求头
                headers = request.get('header', [])
                if headers:
                    md_lines.append(f"\n**Headers:**\n\n```json\n{json.dumps(headers, indent=2)}\n```\n")
                
                # 请求体
                body = request.get('body', {}).get('raw', '')
                if body:
                    md_lines.append(f"\n**Body:**\n\n```json\n{body}\n```\n")
            
            # 递归处理子文件夹
            if 'item' in item:
                process_items(item['item'], level + 1)
            
            md_lines.append("\n---\n")
    
    if 'item' in data:
        process_items(data['item'])
    
    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.writelines(md_lines)
    
    print(f"已生成: {output_md_path}")

# 使用示例
postman_to_markdown('你的集合文件.json', 'output.md')