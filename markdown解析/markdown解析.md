~~~java
package cn.theshuai.markdown;

import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;

import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.List;

public class MultiSheetExporter {

    public static void main(String[] args) throws Exception {

        String markdown =
                "## 利润表\n" +
                        "<table>\n" +
                        "  <tr><th>项目</th><th>金额</th></tr>\n" +
                        "  <tr><td>营业收入</td><td>10000稻别</td></tr>\n" +
                        "</table>\n" +

                        "## 资产负债表\n" +
                        "<table>\n" +
                        "  <tr><th>项目</th><th>金额</th></tr>\n" +
                        "  <tr><td>现金</td><td>20000</td></tr>\n" +
                        "</table>\n" +

                        "## 垃圾表\n" +
                        "<table border=1 style=''>\n" +
                        "  <tr><td style=''>项目</td><th>金额</th></tr>\n" +
                        "  <tr><td>现金</td><td>20000</td></tr>\n" +
                        "</table>\n" +

                        "## 现金流量表\n" +
                        "<table>\n" +
                        "  <tr><th>项目</th><th>金额</th></tr>\n" +
                        "  <tr><td>经营现金流</td><td>3000</td></tr>\n" +
                        "</table>";

        export(markdown);

        System.out.println("导出完成！");
    }

    public static void export(String markdown) throws Exception {

        Workbook wb = new XSSFWorkbook();

        String[] lines = markdown.split("\n");

        String currentTitle = null;
        List<String[]> currentTable = null;

        for (String line : lines) {
            line = line.trim();

            // 遇到 ## 标题
            if (line.startsWith("## ")) {
                // 如果有上一个表格，先导出
                if (currentTitle != null && currentTable != null && !currentTable.isEmpty()) {
                    createSheet(wb, currentTitle, currentTable);
                }

                currentTitle = line.substring(3).trim();
                currentTable = new ArrayList<>();
                System.out.println("发现标题: " + currentTitle);
                continue;
            }

            // 解析表格行
            if (currentTitle != null && line.contains("<tr>")) {
                // 提取所有 <th> 和 <td>
                String[] cells = line.split("</t[hd]>\\s*<t[hd]>|</t[hd]>\\s*<t[hd]>|<t[hd]>|</t[hd]>");
                List<String> cellList = new ArrayList<>();

                // 用正则提取更准确
                java.util.regex.Matcher m = java.util.regex.Pattern.compile("<t[hd]>(.*?)</t[hd]>").matcher(line);
                String[] row = new String[10]; // 假设最多10列
                int colIndex = 0;
                while (m.find()) {
                    row[colIndex++] = m.group(1).trim();
                }

                if (colIndex > 0) {
                    String[] actualRow = new String[colIndex];
                    System.arraycopy(row, 0, actualRow, 0, colIndex);
                    currentTable.add(actualRow);
                }
            }
        }

        // 处理最后一个表格
        if (currentTitle != null && currentTable != null && !currentTable.isEmpty()) {
            createSheet(wb, currentTitle, currentTable);
        }

        try (FileOutputStream fos = new FileOutputStream("test.xlsx")) {
            wb.write(fos);
        }

        wb.close();
    }

    private static void createSheet(Workbook wb, String title, List<String[]> tableData) {
        System.out.println("创建Sheet: " + title + " (" + tableData.size() + "行)");

        Sheet sheet = wb.createSheet(safeSheetName(title));

        for (int r = 0; r < tableData.size(); r++) {
            Row row = sheet.createRow(r);
            String[] cells = tableData.get(r);
            for (int c = 0; c < cells.length; c++) {
                row.createCell(c).setCellValue(cells[c]);
            }
        }

        // 列宽自适应
        if (!tableData.isEmpty()) {
            for (int c = 0; c < tableData.get(0).length; c++) {
                sheet.autoSizeColumn(c);
            }
        }
    }

    private static String safeSheetName(String name) {
        String safe = name.replaceAll("[\\\\/?*\\[\\]]", "");
        if (safe.length() > 31) {
            safe = safe.substring(0, 31);
        }
        return safe;
    }
}
~~~

