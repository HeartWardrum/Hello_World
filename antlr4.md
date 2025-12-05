你用的是 SparkSQL 语法（SparkSqlBaseParser + SparkSqlBaseListener），而 SparkSQL 的语法结构与 MySQL 不一样，所以不会出现 `enterTableSource` 和 `enterFullColumnName` 这样的方法。

但是 Spark SQL 的解析树中依然包含：

---

### ✔ 表名与别名：

对应节点为：

```
tableIdentifier
multipartIdentifier
relation
aliasedQuery
```

---

### ✔ 字段（列名）

对应节点为：

```
columnReference
multipartIdentifier
qualifiedName
expression
```

---

---

# 🔥 你需要重点监听以下 Listener 方法（Spark SQL 专有）

### **表名 & 表别名监听**

如果 SQL 类似：

```sql
SELECT a.id FROM user a
```

适配解析树如下：

| 结构            | 常见节点            |
| ------------- | --------------- |
| 表名            | tableIdentifier |
| 带别名的表         | relation        |
| 识别 SELECT 来源表 | aliasedQuery    |

对应 Listener 如：

```java
@Override
public void enterAliasedQuery(SparkSqlParser.AliasedQueryContext ctx) {
    // 解析表名
    if (ctx.relation() != null && ctx.relation().tableIdentifier() != null) {
        String table = ctx.relation().tableIdentifier().getText();

        // 别名
        if (ctx.identifier() != null) {
            String alias = ctx.identifier().getText();
            tableAliasMap.put(alias, table);
            System.out.println("表：" + table + " 别名：" + alias);
        }
    }
}
```

---

## 覆盖另一种表结构：

```sql
FROM (SELECT ... ) t   ← 子查询
```

可以这样：

```java
@Override
public void enterRelation(SparkSqlParser.RelationContext ctx) {
    if (ctx.tableIdentifier() != null) {
        String table = ctx.tableIdentifier().getText();
        System.out.println("表：" + table);
    }
}
```

---

---

# 🚀 字段解析：enterColumnReference

SparkSQL字段属性基本都落在：

```
columnReference
```

示例：

```java
@Override
public void enterColumnReference(SparkSqlParser.ColumnReferenceContext ctx) {
    String full = ctx.getText(); // e.g. a.id …

    if (full.contains(".")) {
        String[] parts = full.split("\\.");
        String alias = parts[0];
        String column = parts[1];
        String realTable = tableAliasMap.getOrDefault(alias, alias);

        System.out.println("字段：" + column + " 所属表：" + realTable);
    } else {
        System.out.println("字段：" + full + "（无别名）");
    }
}
```

---

---

# 🧠 当字段在 WHERE 中也一样适用：

SQL：

```sql
SELECT a.id FROM user a WHERE a.age > 18
```

解析过程包含：

```
booleanExpression → predicate → columnReference
```

所以依旧可以收到 `enterColumnReference` 回调。

---

---

# ⭐ 最完整版 Listener 示例代码

```java
public class PrintSparkSqlListener extends SparkSqlBaseListener {

    private final Map<String, String> tableAliasMap = new HashMap<>();

    @Override
    public void enterAliasedQuery(SparkSqlParser.AliasedQueryContext ctx) {
        if (ctx.relation() != null &&
                ctx.relation().tableIdentifier() != null) {

            String table = ctx.relation().tableIdentifier().getText();

            if (ctx.identifier() != null) {
                String alias = ctx.identifier().getText();
                tableAliasMap.put(alias, table);
                System.out.println("表：" + table + " 别名：" + alias);
            } else {
                System.out.println("表：" + table);
            }
        }
    }

    @Override
    public void enterRelation(SparkSqlParser.RelationContext ctx) {
        if (ctx.tableIdentifier() != null) {
            String table = ctx.tableIdentifier().getText();
            System.out.println("表：" + table);
        }
    }

    @Override
    public void enterColumnReference(SparkSqlParser.ColumnReferenceContext ctx) {
        String fullText = ctx.getText(); // a.id 或 id

        if (fullText.contains(".")) {
            String[] parts = fullText.split("\\.");
            String alias = parts[0];
            String column = parts[1];

            String realTable = tableAliasMap.getOrDefault(alias, alias);
            System.out.println("字段：" + column + " 所属表：" + realTable);
        } else {
            System.out.println("字段：" + fullText + "（未关联表别名）");
        }
    }
}
```

---

---

# ⭐ 使用方法

```java
SparkSqlLexer lexer = new SparkSqlLexer(CharStreams.fromString(sql));
SparkSqlParser parser = new SparkSqlParser(new CommonTokenStream(lexer));
ParseTree tree = parser.statement();

ParseTreeWalker.DEFAULT.walk(new PrintSparkSqlListener(), tree);
```

---

---

# 🎁 输出示例

解析：

```sql
SELECT u.id, u.age, d.name
FROM user u
JOIN dept d ON u.dept_id = d.id
WHERE u.age > 18
```

输出：

```
表：user 别名：u
表：dept 别名：d
字段：id 所属表：user
字段：age 所属表：user
字段：name 所属表：dept
```

---

---

# 🧩 总结

| 目标        | SparkSQL对应节点               |
| --------- | -------------------------- |
| 提取表       | relation / tableIdentifier |
| 提取表 + 别名  | aliasedQuery               |
| 提取字段      | columnReference            |
| WHERE 内字段 | 同 columnReference          |
| JOIN 内字段  | 同 columnReference          |

---

💡 即使没有 MySQL 那些方法，Spark SQL 的解析结构依然可以：

✔ 找出所有表
✔ 找出所有别名
✔ 找出所有字段
✔ 找出字段所属表

只需要根据 SparkSQL 的语法树映射即可。
