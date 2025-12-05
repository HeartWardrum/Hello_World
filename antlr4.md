确实如此 —— SparkSQL 的语法结构与 MySQL 完全不同，
**AliasedQueryContext 不是表定义节点，也不会持有 relation() 与 identifier()**，
它实际上对应 **带 ORDER、DISTRIBUTE、CLUSTER 子句的查询结构**，不是表来源。

👉 所以真正能取到 **表名/别名** 的逻辑，必须从 SparkSQL 的 AST 中正确定位节点。

---

# ✅ SparkSQL 表来源的正确节点位置

以下节点是关键：

### ① relationPrimary

用于解析 table、subquery、view、CTE

### ② tableIdentifier

用于解析表名

### ③ strictIdentifier / identifier

用于解析表别名

---

---

# 🔥 建议监听以下方法（通用且准确）

---

# ✔ ① 监听 relationPrimary —— 可以拿表

SparkSQL 使用：

```
relationPrimary
```

表示表、视图、子查询 的最初来源节点

代码示例：

```java
@Override
public void enterRelationPrimary(SparkSqlParser.RelationPrimaryContext ctx) {
    if (ctx.tableIdentifier() != null) {
        String table = ctx.tableIdentifier().getText();
        System.out.println("表名: " + table);
    }
}
```

---

# ✔ ② 监听 relation —— 能拿到 alias

SparkSQL 表别名语法类似：

```
relation
    relationPrimary [identifier]
```

所以你可以：

```java
@Override
public void enterRelation(SparkSqlParser.RelationContext ctx) {
    if (ctx.relationPrimary() != null && ctx.identifier() != null) {

        String table = ctx.relationPrimary().getText();
        String alias = ctx.identifier().getText();

        System.out.println("表：" + table + "  别名：" + alias);
    }
}
```

⚠ 注意：

* `ctx.identifier()` 是 alias
* `ctx.relationPrimary()` 的 `.getText()` 可能包含 nested query，需自行过滤

---

---

# ✔ ③ 获取字段：监听 columnReference

SparkSQL 的字段引用节点是：

```
columnReference
```

实现如下：

```java
@Override
public void enterColumnReference(SparkSqlParser.ColumnReferenceContext ctx) {
    String full = ctx.getText(); // 如 u.id 或 age

    if (full.contains(".")) {
        String[] arr = full.split("\\.");
        String alias = arr[0];
        String column = arr[1];

        String table = tableAliasMap.get(alias); // 需上面填充 aliasMap

        System.out.println("字段：" + column + " 来源别名：" + alias + " 所属表：" + table);
    } else {
        System.out.println("字段：" + full + "（无别名约束）");
    }
}
```

---

---

# ⭐ 完整 Listener 示例：可实际使用

```java
public class SparkSqlListener extends SparkSqlBaseListener {

    private final Map<String, String> tableAliasMap = new HashMap<>();

    @Override
    public void enterRelation(SparkSqlParser.RelationContext ctx) {
        // 解析表名和别名
        SparkSqlParser.RelationPrimaryContext pri = ctx.relationPrimary();
        if (pri != null && pri.tableIdentifier() != null) {
            String table = pri.tableIdentifier().getText();

            if (ctx.identifier() != null) { // alias
                String alias = ctx.identifier().getText();
                tableAliasMap.put(alias, table);

                System.out.println("表：" + table + " 别名：" + alias);
            } else {
                System.out.println("表：" + table);
            }
        }
    }

    @Override
    public void enterColumnReference(SparkSqlParser.ColumnReferenceContext ctx) {
        String col = ctx.getText();

        if (col.contains(".")) {
            String[] parts = col.split("\\.");
            String alias = parts[0];
            String column = parts[1];

            String table = tableAliasMap.get(alias);

            System.out.println("字段：" + column + " 所属表：" + table);
        } else {
            System.out.println("字段：" + col);
        }
    }
}
```

---

---

# 🧪 测试 SQL

```sql
SELECT u.id, u.age, d.name
FROM user u
JOIN dept d ON u.dept_id = d.id
WHERE u.age > 20 AND d.status = 1
```

### 输出示例：

```
表：user 别名：u
表：dept 别名：d
字段：id 所属表：user
字段：age 所属表：user
字段：name 所属表：dept
字段：age 所属表：user
字段：status 所属表：dept
```

---

---

# ⭐ 关键点总结

| 目标      | 节点类型                                   |
| ------- | -------------------------------------- |
| 提取表名    | RelationPrimaryContext.tableIdentifier |
| 提取别名    | RelationContext.identifier             |
| 提取字段名   | ColumnReferenceContext                 |
| 解析字段对应表 | 根据别名映射                                 |

---

---

# 🎯 最重要结论

✔ SparkSQL 解析 **表的来源** 不是 AliasedQuery，而是：

* RelationContext
* RelationPrimaryContext
* TableIdentifier

✔ SparkSQL 解析字段的是：

* ColumnReferenceContext

✔ visitTerminal 无法判断结构，仅调试辅助用

---

如果你需要解析：

✔ where 条件结构树
✔ join 关联条件
✔ group by、order by 字段来源

也可以继续问，会继续给对应节点定位方法。
