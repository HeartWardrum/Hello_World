import os
import pandas as pd
from docx import Document


def extract_word_tables_to_excel(word_path, excel_path):
    # 加载 Word 文档
    doc = Document(word_path)

    # 存储所有表格解析后的数据，每个元素是一个字典（对应 Excel 的一行）
    all_data = []

    # 遍历文档中的所有表格
    for table_idx, table in enumerate(doc.tables):
        row_data = {}

        # 遍历当前表格的每一行
        for row in table.rows:
            # 记录当前行里，我们处理到了第几个单元格（从1开始计数）
            cell_counter = 1

            current_key = None

            # 遍历当前行的所有单元格
            for cell in row.cells:
                # 除去前后空格和换行
                text = cell.text.strip()

                if cell_counter % 2 != 0:
                    # 单数列：作为标题（Key）
                    # 如果单元格为空，可以给个默认值防止报错
                    current_key = text if text else f"未知字段_{cell_counter}"
                else:
                    # 双数列：作为数据值（Value）
                    # 只有在有对应标题的情况下才写入
                    if current_key:
                        row_data[current_key] = text
                        # 重置 key，防止有些特殊行结构异常
                        current_key = None

                cell_counter += 1

        # 如果这个表格成功提取到了数据，就加入大列表
        if row_data:
            all_data.append(row_data)
        else:
            print(f"提示：第 {table_idx + 1} 个表格似乎是空的或格式不符，已跳过。")

    if not all_data:
        print("未能在 Word 中提取到任何有效数据！")
        return

    # 使用 pandas 转换为 DataFrame
    # Pandas 会自动汇总所有出现过的 Key 作为 Excel 的列名，并把每行的数据对齐
    df = pd.DataFrame(all_data)

    # 导出为 Excel 文件
    df.to_excel(excel_path, index=False)
    print(
        f"成功！已将 {len(all_data)} 个表格的数据导出至 Excel 文件的单个 Sheet 中。"
    )
    print(f"文件路径: {os.path.abspath(excel_path)}")


# ==================== 使用示例 ====================
if __name__ == "__main__":
    # 替换为你的 Word 文件路径
    word_file = "你的文档.docx"
    # 想要生成的 Excel 文件路径
    excel_file = "导出结果.xlsx"

    # 执行转换
    if os.path.exists(word_file):
        extract_word_tables_to_excel(word_file, excel_file)
    else:
        print(
            f"错误：找不到输入的 Word 文件 '{word_file}'，请检查路径是否正确。"
        )