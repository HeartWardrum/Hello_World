好的 — 既然你在运行时发现 `ctx.tableIdentifier()` / `ctx.identifier()` 这些方法不可用，那说明你当前使用的 `SqlBaseParser` 的生成类里，这些子规则没有被生成成直接的访问器（不同版本/不同 g4 写法会造成这种差异）。别担心，仍然可以 **稳健地从 `RelationContext` 里找到表名和别名**，方法是：**以“遍历/匹配子节点类型或文本”为主**，而不是依赖特定的自动生成方法。

下面给出两部分内容：

1. 快速的调试方法 — 打印 `RelationContext` 的子节点结构，确认子节点类名/文本；
2. 稳健的提取实现 — 在 listener 里通过检查子节点类型/文本来识别表名和别名（兼容没有直接访问器的情况）。

---

## 1) 调试：打印 RelationContext 的结构（先看清楚 AST 长啥样）

把下面方法临时加到 listener 里，跑一下 SQL，输出会告诉你每个子节点是什么类、文本是什么：

```java
private void debugPrintChildren(ParserRuleContext ctx) {
    System.out.println("=== " + ctx.getClass().getSimpleName() + " children ===");
    for (int i = 0; i < ctx.getChildCount(); i++) {
        ParseTree child = ctx.getChild(i);
        String cls = child.getClass().getSimpleName();
        String text = child.getText();
        System.out.println("child[" + i + "] class=" + cls + " text=\"" + text + "\"");
        if (child instanceof ParserRuleContext) {
            ParserRuleContext pr = (ParserRuleContext) child;
            System.out.println("    ruleIndex=" + pr.getRuleIndex()); // 可映射到 parser.ruleNames[]
        } else if (child instanceof TerminalNode) {
            TerminalNode tn = (TerminalNode) child;
            System.out.println("    token=" + tn.getSymbol().getType() + " tokenText=" + tn.getText());
        }
    }
}
```

在 `enterRelation(SqlBaseParser.RelationContext ctx)` 里调用 `debugPrintChildren(ctx);`，你会看到实际子节点类名（比如 `QualifiedNameContext`、`RelationPrimaryContext`、`TerminalNodeImpl` 等）和文本。根据输出你就能确定“哪个子节点是表名、哪个是别名”。

---

## 2) 稳健的提取实现（兼容无访问器的情况）

下面的 Listener 代码示例，不依赖 `ctx.tableIdentifier()` / `ctx.identifier()` 方法，而是通过**查找子节点中第一个符合“可能是表名”的子规则**（比如 `qualifiedName` / `identifier` / `multipartIdentifier` 等类名）并把最后一个终结符当作 alias（如果存在）：

```java
public class SqlBaseRobustListener extends SqlBaseParserBaseListener {

    private final Map<String, String> tableAliasMap = new HashMap<>();

    @Override
    public void enterRelation(SqlBaseParser.RelationContext ctx) {
        // 调试用：查看子节点
        // debugPrintChildren(ctx);

        // 1. 尝试从 relationPrimary / first child 中找表名节点
        String tableName = null;
        String alias = null;

        // 如果 relationPrimary 存在，优先在其下找 qualifiedName 或 identifier
        for (int i = 0; i < ctx.getChildCount(); i++) {
            ParseTree child = ctx.getChild(i);

            // 若是 ParserRuleContext，查看类名以判断
            if (child instanceof ParserRuleContext) {
                String cname = child.getClass().getSimpleName();

                // 常见包含表名的 node 名称（可能因 g4 不同而不同）
                if (cname.endsWith("RelationPrimaryContext") || cname.endsWith("RelationPrimary")) {
                    // 在 relationPrimary 下找第一个 identifier / qualifiedName
                    tableName = findNameInCtx((ParserRuleContext) child);
                } else if (cname.endsWith("QualifiedNameContext")
                        || cname.endsWith("MultipartIdentifierContext")
                        || cname.endsWith("TableIdentifierContext")
                        || cname.endsWith("IdentifierContext")) {
                    // 直接就是表名形式
                    tableName = child.getText();
                }
            } else if (child instanceof TerminalNode) {
                // 有些语法把 alias 以终结符放最后
                // 这里我们不马上判定，等后面统一处理
            }
        }

        // 2. 尝试从 ctx 的最后几个子节点猜 alias（如果有的话）
        // 常见形式: relationPrimary identifier
        if (ctx.getChildCount() >= 2) {
            ParseTree last = ctx.getChild(ctx.getChildCount() - 1);
            if (last instanceof TerminalNode) {
                String txt = last.getText();
                // 过滤掉关键字和符号，基本把纯字母/下划线作为 alias
                if (txt.matches("[A-Za-z_][A-Za-z0-9_]*")) {
                    alias = txt;
                }
            } else if (last instanceof ParserRuleContext) {
                String lname = last.getClass().getSimpleName();
                if (lname.endsWith("IdentifierContext") || lname.endsWith("Identifier")) {
                    alias = last.getText();
                }
            }
        }

        // 3. 记录并输出
        if (tableName != null) {
            if (alias != null) {
                tableAliasMap.put(alias, tableName);
                System.out.println("表: " + tableName + " 别名: " + alias);
            } else {
                System.out.println("表: " + tableName);
            }
        }
    }

    @Override
    public void enterQualifiedName(SqlBaseParser.QualifiedNameContext ctx) {
        // 该节点通常也会在 SELECT/WHERE 中出现，代表列或带前缀的名字
        String text = ctx.getText(); // 可能是 a.id 或 db.table
        if (text.contains(".")) {
            String[] parts = text.split("\\.");
            String left = parts[0];
            String column = parts[parts.length - 1]; // 支持多级
            String resolvedTable = tableAliasMap.getOrDefault(left, left);
            System.out.println("字段: " + column + " -> 来源: " + left + " -> 所属表: " + resolvedTable);
        } else {
            System.out.println("字段: " + text + "（未指定来源）");
        }
    }

    // 辅助：在某个 ParserRuleContext 下寻找第一个合适的 name（identifier / qualifiedName 等）
    private String findNameInCtx(ParserRuleContext ctx) {
        for (int i = 0; i < ctx.getChildCount(); i++) {
            ParseTree ch = ctx.getChild(i);
            if (ch instanceof ParserRuleContext) {
                String cname = ch.getClass().getSimpleName();
                if (cname.endsWith("QualifiedNameContext")
                        || cname.endsWith("IdentifierContext")
                        || cname.endsWith("TableIdentifierContext")
                        || cname.endsWith("MultipartIdentifierContext")) {
                    return ch.getText();
                }
                // 递归查找
                String rec = findNameInCtx((ParserRuleContext) ch);
                if (rec != null) return rec;
            } else if (ch instanceof TerminalNode) {
                String t = ch.getText();
                if (t.matches("[A-Za-z_][A-Za-z0-9_]*")) {
                    // 可能是简单的表名（谨慎返回）
                    return t;
                }
            }
        }
        return null;
    }

    // 可选：调试打印函数（如前所示）
    private void debugPrintChildren(ParserRuleContext ctx) {
        System.out.println("=== " + ctx.getClass().getSimpleName() + " children ===");
        for (int i = 0; i < ctx.getChildCount(); i++) {
            ParseTree child = ctx.getChild(i);
            System.out.println("child[" + i + "] class=" + child.getClass().getSimpleName() + " text=\"" + child.getText() + "\"");
        }
    }
}
```

---

## 3) 为什么会出现“没有方法”的情况（简要说明）

* ANTLR 生成的解析器 API 与 grammar 的写法直接相关：如果 `SqlBase.g4` 用的是 `tableIdentifier` 作为某个子规则名但并没有被直接命名为 `tableIdentifier`（或该子规则被内嵌/重命名），就不会生成 `ctx.tableIdentifier()` 访问器。
* 不同 Spark / Hive / Presto 等 `sqlbase` grammar 版本差异很大，方法名也会不一样。
* 因此，不要完全依赖特定版本的自动 getter，而用更通用的“按子节点类型或文本”方法更可靠，兼容性更好。

---

## 4) 调试建议（实践步骤）

1. 先用 `debugPrintChildren(ctx)` 在 `enterRelation` 打印真实结构，确认哪一个子节点确实是表名与别名；
2. 根据打印结果调整 `findNameInCtx` 的匹配策略（比如有些版本是 `multipartIdentifier`、有些叫 `identifier`、有些叫 `qualifiedName`）；
3. 用 `enterQualifiedName` / `enterDereferenceExpression` 等去捕获 SELECT/WHERE 中的列引用；
4. 用 alias map 把列左边的前缀解析为真实表名。

---

如果你把 `debugPrintChildren(ctx)` 在 `enterRelation` 的输出贴上来（直接把几行输出贴到这里），我可以根据真实的子节点类名和文本，给你一段严格匹配你当前 grammar 的提取代码（直接可用）。
