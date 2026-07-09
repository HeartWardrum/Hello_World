import re

import openpyxl
from openpyxl.cell.rich_text import CellRichText, TextBlock
import pandas as pd

CIRCLED_NUM_BREAK = re.compile(r"([②-⑳])")


def is_bold(font, cell_font=None):
    """InlineFont.bold 为 None 时，回退到单元格字体"""
    if font is not None and font.bold is not None:
        return bool(font.bold)
    if cell_font is not None and cell_font.bold is not None:
        return bool(cell_font.bold)
    return False


def plain_text_cell(cell):
    """提取单元格纯文本，不转换加粗标签（用于标题行）"""
    if cell.value is None:
        return ""
    if isinstance(cell.value, CellRichText):
        return "".join(
            block if isinstance(block, str) else block.text
            for block in cell.value
        )
    return str(cell.value)


def parse_rich_text_cell(cell):
    """
    核心解析函数：提取单个单元格中富文本的加粗片段并转化为 HTML <b> 标签
    """
    if cell.value is None:
        return ""

    if isinstance(cell.value, CellRichText):
        html_fragments = []
        for block in cell.value:
            if isinstance(block, str):
                text, font = block, None
            elif isinstance(block, TextBlock):
                text, font = block.text, block.font
            else:
                text, font = str(block), None

            if not text:
                continue
            if is_bold(font, cell.font):
                html_fragments.append(f"<b>{text}</b>")
            else:
                html_fragments.append(text)
        return "".join(html_fragments)

    val_str = str(cell.value)
    if is_bold(None, cell.font):
        return f"<b>{val_str}</b>"
    return val_str


def apply_circled_number_breaks(text: str) -> str:
    """在 ②-⑳ 前插入换行与缩进，① 前不插入"""
    return CIRCLED_NUM_BREAK.sub(r"<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;\1", text)


def read_all_sheets_with_richtext(file_path):
    """
    读取 Excel 文件中的所有 Sheet 页，并解析其中的富文本加粗标签。
    返回一个字典：{"SheetName": DataFrame}
    """
    wb = openpyxl.load_workbook(file_path, data_only=False, rich_text=True)

    all_sheets_dict = {}

    for sheet_name in wb.sheetnames:
        print(f"正在解析 Sheet: {sheet_name} ...")
        ws = wb[sheet_name]

        sheet_data = []
        for row_idx, row in enumerate(ws.iter_rows(values_only=False)):
            if row_idx == 0:
                row_data = [plain_text_cell(cell) for cell in row]
            else:
                row_data = [
                    apply_circled_number_breaks(parse_rich_text_cell(cell))
                    for cell in row
                ]
            sheet_data.append(row_data)

        if not sheet_data:
            all_sheets_dict[sheet_name] = pd.DataFrame()
            continue

        df = pd.DataFrame(sheet_data[1:], columns=sheet_data[0])
        all_sheets_dict[sheet_name] = df

    print("所有 Sheet 页解析完毕！")
    return all_sheets_dict


# ==========================================
#                  如何使用
# ==========================================
if __name__ == "__main__":
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_colwidth', None)

    excel_path = "test.xlsx"

    sheets_data = read_all_sheets_with_richtext(excel_path)

    print("\n成功读取的 Sheet 列表:", list(sheets_data.keys()))
    print("-" * 50)

    first_sheet_name = list(sheets_data.keys())[0]
    print(f"展示第一个 Sheet ({first_sheet_name}) 的前几行数据：")
    print(sheets_data[first_sheet_name].head())
