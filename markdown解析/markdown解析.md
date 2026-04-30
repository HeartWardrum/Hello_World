~~~java
import com.vladsch.flexmark.ast.Node;
import com.vladsch.flexmark.ext.tables.TableBlock;
import com.vladsch.flexmark.ext.tables.TableCell;
import com.vladsch.flexmark.ext.tables.TableRow;
import com.vladsch.flexmark.ext.tables.TablesExtension;
import com.vladsch.flexmark.parser.Parser;
import com.vladsch.flexmark.util.data.MutableDataSet;
import com.vladsch.flexmark.util.ast.NodeVisitor;
import com.vladsch.flexmark.util.ast.VisitHandler;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.stream.Collectors;

public class MarkdownToCsvConverter {
    
    private final Parser parser;
    
    public MarkdownToCsvConverter() {
        MutableDataSet options = new MutableDataSet();
        options.set(Parser.EXTENSIONS, Collections.singletonList(TablesExtension.create()));
        this.parser = Parser.builder(options).build();
    }
    
    /**
     * 从Markdown内容中提取所有表格
     */
    public List<Table> extractTables(String markdown) {
        List<Table> tables = new ArrayList<>();
        Node document = parser.parse(markdown);
        
        NodeVisitor visitor = new NodeVisitor(
            new VisitHandler<>(TableBlock.class, node -> {
                Table table = new Table();
                Node child = node.getFirstChild();
                boolean isFirstRow = true;
                
                while (child != null) {
                    if (child instanceof TableRow) {
                        TableRow row = (TableRow) child;
                        List<String> rowData = new ArrayList<>();
                        
                        Node cell = row.getFirstChild();
                        while (cell != null) {
                            if (cell instanceof TableCell) {
                                // 获取单元格纯文本内容
                                String cellText = cell.getChars().toString().trim();
                                // CSV转义处理
                                rowData.add(escapeCsv(cellText));
                            }
                            cell = cell.getNext();
                        }
                        
                        if (isFirstRow) {
                            table.headers = rowData;
                            isFirstRow = false;
                        } else {
                            table.rows.add(rowData);
                        }
                    }
                    child = child.getNext();
                }
                
                if (!table.headers.isEmpty()) {
                    tables.add(table);
                }
            })
        );
        
        visitor.visit(document);
        return tables;
    }
    
    /**
     * 将单个表格转换为CSV字符串
     */
    public String tableToCsv(Table table) {
        List<String> lines = new ArrayList<>();
        
        // 添加表头
        lines.add(String.join(",", table.headers));
        
        // 添加数据行
        for (List<String> row : table.rows) {
            // 确保行的列数与表头一致
            List<String> paddedRow = new ArrayList<>(row);
            while (paddedRow.size() < table.headers.size()) {
                paddedRow.add("");  // 空单元格补空字符串
            }
            lines.add(String.join(",", paddedRow));
        }
        
        return String.join("\n", lines);
    }
    
    /**
     * 将所有表格保存为独立的CSV文件
     * @param markdownFile Markdown文件路径
     * @param outputDir 输出目录
     * @return 生成的文件列表
     */
    public List<Path> convertToCsvFiles(String markdownFile, String outputDir) throws IOException {
        Path mdPath = Paths.get(markdownFile);
        if (!Files.exists(mdPath)) {
            throw new IllegalArgumentException("文件不存在: " + markdownFile);
        }
        
        String markdown = Files.readString(mdPath);
        List<Table> tables = extractTables(markdown);
        
        List<Path> outputFiles = new ArrayList<>();
        Path outputDirectory = Paths.get(outputDir);
        
        if (!Files.exists(outputDirectory)) {
            Files.createDirectories(outputDirectory);
        }
        
        String baseName = mdPath.getFileName().toString().replace(".md", "");
        
        for (int i = 0; i < tables.size(); i++) {
            String csvContent = tableToCsv(tables.get(i));
            String fileName = (tables.size() == 1) 
                ? baseName + ".csv" 
                : baseName + "_table_" + (i + 1) + ".csv";
            
            Path csvPath = outputDirectory.resolve(fileName);
            Files.writeString(csvPath, csvContent);
            outputFiles.add(csvPath);
            System.out.println("✅ 已生成: " + csvPath);
        }
        
        if (tables.isEmpty()) {
            System.out.println("⚠️ 未找到表格");
        }
        
        return outputFiles;
    }
    
    /**
     * CSV转义：处理包含逗号、引号、换行符的字段
     */
    private String escapeCsv(String field) {
        if (field == null) return "";
        
        // 检查是否需要转义
        boolean needEscape = field.contains(",") 
                          || field.contains("\"") 
                          || field.contains("\n") 
                          || field.contains("\r");
        
        if (!needEscape) {
            return field;
        }
        
        // 双引号转义为两个双引号
        String escaped = field.replace("\"", "\"\"");
        return "\"" + escaped + "\"";
    }
    
    /**
     * 表格数据类
     */
    public static class Table {
        List<String> headers = new ArrayList<>();
        List<List<String>> rows = new ArrayList<>();
        
        public List<String> getHeaders() {
            return headers;
        }
        
        public List<List<String>> getRows() {
            return rows;
        }
        
        public int getColumnCount() {
            return headers.size();
        }
        
        public int getRowCount() {
            return rows.size();
        }
        
        @Override
        public String toString() {
            return String.format("Table[%d columns, %d rows]", getColumnCount(), getRowCount());
        }
    }
}
~~~

~~~java
public class Main {
    public static void main(String[] args) {
        MarkdownToCsvConverter converter = new MarkdownToCsvConverter();
        
        try {
            // 方式1：转换整个文件中的所有表格
            List<Path> outputs = converter.convertToCsvFiles(
                "./docs/report.md",   // Markdown文件
                "./output/csv"         // CSV输出目录
            );
            
            System.out.println("共生成 " + outputs.size() + " 个CSV文件");
            
            // 方式2：手动处理表格数据
            String markdown = """
                # 销售报告
                
                | 产品 | Q1销量 | Q2销量 | Q3销量 |
                |------|--------|--------|--------|
                | 手机 | 1200   | 1500   | 1800   |
                | 平板 | 800    | 950    | 1100   |
                | 手表 | 500    | 600    | 700    |
                
                以下是另一个表格：
                
                | 部门 | 人数 | 平均年龄 |
                |------|------|----------|
                | 技术部 | 25 | 28.5 |
                | 市场部 | 15 | 32.0 |
                """;
            
            List<MarkdownToCsvConverter.Table> tables = converter.extractTables(markdown);
            
            for (int i = 0; i < tables.size(); i++) {
                System.out.println("\n表格 " + (i + 1) + ": " + tables.get(i));
                String csv = converter.tableToCsv(tables.get(i));
                System.out.println(csv);
            }
            
        } catch (Exception e) {
            System.err.println("转换失败: " + e.getMessage());
            e.printStackTrace();
        }
    }
}
~~~

~~~java
public class AdvancedCsvConverter extends MarkdownToCsvConverter {
    
    /**
     * 使用自定义分隔符（如制表符\t、分号;等）
     */
    public String tableToCsv(Table table, String delimiter) {
        List<String> lines = new ArrayList<>();
        
        // 表头
        lines.add(String.join(delimiter, table.headers));
        
        // 数据行
        for (List<String> row : table.rows) {
            List<String> paddedRow = new ArrayList<>(row);
            while (paddedRow.size() < table.headers.size()) {
                paddedRow.add("");
            }
            lines.add(String.join(delimiter, paddedRow));
        }
        
        return String.join("\n", lines);
    }
    
    /**
     * 导出为Excel兼容的CSV（带BOM的UTF-8）
     */
    public void exportToExcel(String markdownFile, String outputPath) throws IOException {
        String markdown = Files.readString(Paths.get(markdownFile));
        List<Table> tables = extractTables(markdown);
        
        if (tables.isEmpty()) {
            throw new IllegalStateException("Markdown文件中没有找到表格");
        }
        
        // 如果多个表格，合并它们（用空行分隔）
        StringBuilder combinedCsv = new StringBuilder();
        for (int i = 0; i < tables.size(); i++) {
            if (i > 0) combinedCsv.append("\n\n");  // 空行分隔不同表格
            combinedCsv.append(tableToCsv(tables.get(i)));
        }
        
        // 添加UTF-8 BOM，让Excel正确识别中文
        byte[] bom = {(byte) 0xEF, (byte) 0xBB, (byte) 0xBF};
        byte[] content = combinedCsv.toString().getBytes("UTF-8");
        byte[] withBom = new byte[bom.length + content.length];
        System.arraycopy(bom, 0, withBom, 0, bom.length);
        System.arraycopy(content, 0, withBom, bom.length, content.length);
        
        Files.write(Paths.get(outputPath), withBom);
        System.out.println("✅ Excel兼容CSV已生成: " + outputPath);
    }
}
~~~

~~~java
public class MultiTableConverter {
    
    public static void main(String[] args) throws Exception {
        MarkdownToCsvConverter converter = new MarkdownToCsvConverter();
        
        // 自动为每个表格生成单独的文件
        // report.md 中有几个表格，就生成几个 CSV 文件
        List<Path> outputs = converter.convertToCsvFiles(
            "./docs/report.md",   // 包含多个表格的Markdown文件
            "./output/csv"         // 输出目录
        );
        
        // 生成的文件：
        // report_table_1.csv  (第1个表格)
        // report_table_2.csv  (第2个表格)
        // report_table_3.csv  (第3个表格)
    }
}
~~~

   

