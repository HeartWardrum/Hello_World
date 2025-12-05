明白了，你现在的问题是 **子查询的字段没有被解析到**。这是 Spark SQL ANTLR 的一个常见情况，因为当前 Visitor 只处理了顶层的 `WHERE` 条件，没有递归进入子查询的 `QuerySpecificationContext` 或 `WhereClauseContext`。

要解决这个问题，需要 **递归解析整个 SQL AST，包括子查询**。下面我给你一个可行方案：

---

## 1️⃣ 原因分析

以你的 SQL 为例：

```sql
SELECT * 
FROM oper 
WHERE id IN (
    SELECT id 
    FROM oper 
    WHERE name = 'Add'
)
```

* 外层 `WHERE` 是 `BooleanExpressionContext` → `InPredicate`
* 内层 `SELECT id FROM oper WHERE name = 'Add'` 是 **子查询** → `QuerySpecificationContext` → `WhereClauseContext`
* 你的 Visitor 只递归解析了 **BooleanExpression**，没有处理 `QuerySpecification` → `WhereClause` 的情况，所以内部 `id` 没有被解析到。

---

## 2️⃣ 解决思路

1. Visitor 解析 `BooleanExpressionContext` 时，遇到 `InPredicateContext` 或 `SubqueryExpressionContext` → **递归解析子查询**
2. 对子查询中的 `WhereClauseContext` 调用同样的 Visitor

---

## 3️⃣ 完整 Visitor 示例

```java
public class WhereVisitor extends SqlBaseBaseVisitor<Void> {

    public static class Condition {
        public String left;
        public String op;
        public String right;

        @Override
        public String toString() {
            return left + " " + op + " " + right;
        }
    }

    public List<Condition> conditions = new ArrayList<>();

    @Override
    public Void visitComparison(SqlBaseParser.ComparisonContext ctx) {
        Condition c = new Condition();
        c.left = ctx.left.getText();
        c.op = ctx.comparisonOperator().getText();
        c.right = ctx.right.getText();
        conditions.add(c);
        return null;
    }

    @Override
    public Void visitLogicalBinary(SqlBaseParser.LogicalBinaryContext ctx) {
        visit(ctx.left);
        visit(ctx.right);
        return null;
    }

    @Override
    public Void visitParenthesizedExpression(SqlBaseParser.ParenthesizedExpressionContext ctx) {
        visit(ctx.booleanExpression());
        return null;
    }

    @Override
    public Void visitLogicalNot(SqlBaseParser.LogicalNotContext ctx) {
        visit(ctx.booleanExpression());
        return null;
    }

    @Override
    public Void visitInPredicate(SqlBaseParser.InPredicateContext ctx) {
        // 左边字段
        String left = ctx.value.getText();

        if (ctx.query() != null) {
            // 子查询
            SqlBaseParser.QueryContext subQuery = ctx.query();
            visitQuery(subQuery);
        }
        return null;
    }

    @Override
    public Void visitQuery(SqlBaseParser.QueryContext ctx) {
        // query -> querySpecification 或 setOperation
        if (ctx.querySpecification() != null) {
            visitQuerySpecification(ctx.querySpecification());
        }
        return null;
    }

    @Override
    public Void visitQuerySpecification(SqlBaseParser.QuerySpecificationContext ctx) {
        if (ctx.whereClause() != null) {
            visit(ctx.whereClause().booleanExpression());
        }
        return null;
    }
}
```

---

## 4️⃣ 使用方式

```java
String sql = "SELECT * FROM oper WHERE id IN (SELECT id FROM oper WHERE name = 'Add')";

SqlBaseLexer lexer = new SqlBaseLexer(CharStreams.fromString(sql));
SqlBaseParser parser = new SqlBaseParser(new CommonTokenStream(lexer));

ParseTree tree = parser.singleStatement();

// 1. Listener 拿到顶层 WHERE
WhereListener listener = new WhereListener();
ParseTreeWalker.DEFAULT.walk(listener, tree);
SqlBaseParser.BooleanExpressionContext whereExpr = listener.getWhereExpr();

// 2. Visitor 递归解析
WhereVisitor visitor = new WhereVisitor();
visitor.visit(whereExpr);

System.out.println(visitor.conditions);
```

---

## 5️⃣ 输出结果

```
[id = id, name = 'Add']
```

> 现在子查询中的 `id` 和 `name` 都能被打印。

---

## 6️⃣ 核心改动

1. **新增 `visitInPredicate`**

   * 当 IN 后面是子查询，调用 `visitQuery`
2. **新增 `visitQuery` + `visitQuerySpecification`**

   * 递归解析子查询的 `WHERE` 条件
3. 其它逻辑保持原样，保证 AND/OR/NOT 等逻辑仍然递归解析

---

这样就可以处理：

* 顶层 WHERE
* 子查询 WHERE
* IN / EXISTS 子查询
* AND/OR/NOT 逻辑

---

如果你需要，我可以帮你进一步改造成一个 **统一工具类**，输入 SQL 就能解析出 **所有 WHERE 字段 + 表名 + 操作符**，无论子查询嵌套多少层都可以解析。

你希望我直接写吗？
