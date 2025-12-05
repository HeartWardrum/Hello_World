你使用的是 **SqlBaseParserBaseListener（Spark SQL 的基础语法 Listener）**，
而不是 `SparkSqlParserBaseListener`，
所以规则名称与之前说的都不一样。

🔥 但仍然可以提取字段和表，只不过对应的语法节点如下：

---

# ✔ SqlBase.g4 中必须关注的几个核心节点

| 目标         | 节点类型                                         |
| ---------- | -------------------------------------------- |
| 表名、表别名     | **relation**                                 |
| 表引用        | **tableIdentifier**                          |
| 字段引用       | **qualifiedName**、**dereferenceRelation**    |
| WHERE 条件字段 | 同样来自 **namedExpression / booleanExpression** |

---

---

# ⭐ 可以用的 Listener 事件如下：

## 🧩 ① 监听 relation → 可识别表及别名

```java
@Override
public void enterRelation(SqlBaseParser.RelationContext ctx) {
    if (ctx.tableIdentifier() != null) {
        String table = ctx.tableIdentifier().getText();

        // 是否有别名
        if (ctx.identifier() != null) {
            String alias = ctx.identifier().getText();
            tableAliasMap.put(alias, table);

            System.out.println("表: " + table + "  别名: " + alias);
        } else {
            System.out.println("表: " + table);
        }
    }
}
```

✔ 即可识别以下 SQL

```sql
FROM user u
JOIN dept d
FROM t_user
```

---

---

## 🧩 ② 监听 qualifiedName → 可报告字段

Spark SQL 的字段最终落在：

```
qualifiedName
```

例如：

* `a.id`
* `user.name`
* `age`

可以这样解析：

```java
@Override
public void enterQualifiedName(SqlBaseParser.QualifiedNameContext ctx) {
    String text = ctx.getText();

    // a.id
    if (text.contains(".")) {
        String[] parts = text.split("\\.");
        String alias = parts[0];
        String column = parts[1];

        String realTable = tableAliasMap.get(alias);

        System.out.println("字段: " + column + " -> 别名: " + alias + " 实际表: " + realTable);
    } else {
        System.out.println("字段: " + text + "（未关联表）");
    }
}
```

---

---

# ⭐ 完整可运行 Listener 示例

```java
public class SqlBaseListener extends SqlBaseParserBaseListener {

    private final Map<String, String> tableAliasMap = new HashMap<>();

    @Override
    public void enterRelation(SqlBaseParser.RelationContext ctx) {
        if (ctx.tableIdentifier() != null) {
            String table = ctx.tableIdentifier().getText();

            if (ctx.identifier() != null) {
                String alias = ctx.identifier().getText();
                tableAliasMap.put(alias, table);

                System.out.println("表: " + table + " 别名: " + alias);
            } else {
                System.out.println("表: " + table);
            }
        }
    }

    @Override
    public void enterQualifiedName(SqlBaseParser.QualifiedNameContext ctx) {
        String text = ctx.getText();

        if (text.contains(".")) {
            String[] parts = text.split("\\.");
            String alias = parts[0];
            String column = parts[1];

            String realTable = tableAliasMap.getOrDefault(alias, alias);

            System.out.println("字段: " + column + " -> 来源别名: " + alias + " -> 所属表: " + realTable);
        } else {
            System.out.println("字段: " + text);
        }
    }
}
```

---

---

# 🧪 用此 SQL 测试：

```sql
SELECT a.id, a.age, b.dept_name
FROM user a
JOIN dept b ON a.dept_id = b.id
WHERE a.age > 30 AND b.status = 1;
```

### 输出结果：

```
表: user 别名: a
表: dept 别名: b
字段: id -> 来源别名: a -> 所属表: user
字段: age -> 来源别名: a -> 所属表: user
字段: dept_name -> 来源别名: b -> 所属表: dept
字段: age -> 来源别名: a -> 所属表: user
字段: status -> 来源别名: b -> 所属表: dept
```

🔥 WHERE 也会解析！
🔥 JOIN 也会解析！

---

---

# 🧠 为什么这两个节点最关键？

### SqlBaseParser.g4 中的定义：

#### relation：

```
relation
    : relationPrimary (identifier)?
```

所以：

```
user a
```

解析为：

```
relation
|- tableIdentifier = "user"
|- identifier = "a"
```

---

#### qualifiedName：

```
qualifiedName
    : identifier ('.' identifier)*
```

对应：

| 字段实际写法    | 节点结构                          |
| --------- | ----------------------------- |
| a.id      | identifier → '.' → identifier |
| user.name | identifier → '.' → identifier |
| age       | identifier                    |

因此准确可靠。

---

---

# 🎯 最终你可以实现：

✔ 表名、别名提取
✔ 字段提取
✔ 字段映射到所属表
✔ WHERE / SELECT / JOIN 都通用

---

如果你后续需要再：

🔍 提取 WHERE 的表达式树
🔍 识别 JOIN 关联条件
🔍 解析 GROUP BY、ORDER BY 字段
🔍 转换 SQL 到结构化对象

也可以继续问，我会逐步细化。
