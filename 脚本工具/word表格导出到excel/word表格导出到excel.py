import os
import pandas as pd
from docx import Document


def extract_word_tables_to_excel(word_path, excel_path):
    doc = Document(word_path)
    all_data = []

    for table_idx, table in enumerate(doc.tables):
        row_data = {}

        for row in table.rows:
            # 用一个集合（set）来记录当前行已经处理过的单元格底层 XML 对象
            seen_tcs = set()

            # 过滤掉由于合并单元格产生的重复“影子格子”
            valid_cells = []
            for cell in row.cells:
                # cell._tc 是底层的 XML 元素，合并单元格的 _tc 是同一个对象
                if cell._tc not in seen_tcs:
                    seen_tcs.add(cell._tc)
                    valid_cells.append(cell)

            # 现在开始对过滤后的真正单元格进行单双数判断
            cell_counter = 1
            current_key = None

            for cell in valid_cells:
                text = cell.text.strip()

                if cell_counter % 2 != 0:
                    # 单数列：标题
                    current_key = text if text else f"未知字段_{cell_counter}"
                else:
                    # 双数列：值
                    if current_key:
                        row_data[current_key] = text
                        current_key = None

                cell_counter += 1

        if row_data:
            all_data.append(row_data)

    if not all_data:
        print("未能在 Word 中提取到任何有效数据！")
        return

    df = pd.DataFrame(all_data)
    df.to_excel(excel_path, index=False)
    print(f"成功！已过滤合并单元格干扰，成功导出 {len(all_data)} 行数据。")


# ==================== 使用示例 ====================
if __name__ == "__main__":
    word_file = "你的文档.docx"
    excel_file = "导出结果.xlsx"

    if os.path.exists(word_file):
        extract_word_tables_to_excel(word_file, excel_file)
    else:
        print(f"错误：找不到输入的 Word 文件 '{word_file}'")