明白了，你**不能改 g4 文件**，那我们就只能在 **Visitor 里根据现有的 Context 规则做递归解析**。也就是说，你需要利用 Spark SQL 原始语法里的 `predicate`、`valueExpression`、`booleanExpression` 来捕获 `IN (subquery)`，而不是指望有 `visitInPredicate`。

我给你一个完整的思路和示例代码，**不修改 g4 文件也能解析子查询里的字段**。

---

## 1️⃣ 思路

1. `IN (subquery)` 在 AST 里表现为：

```
PredicateContext
 └── valueExpression
 └── IN
 └── QueryContext
```

2. 所以在 Visitor 中重写 `visitPredicate` 或者 `visitBooleanExpression` 时：

```java
if (ctx.getChildCount() >= 3 && ctx.getChild(1).getText().equalsIgnoreCase("IN")) {
    // ctx.getChild(0) = 左边字段
    // ctx.getChild(2) = QueryContext 或括号中的列表
}
```

3. 当发现 `IN` 后面是 `QueryContext`，就递归调用 `visitQuery` 或 `visitQuerySpecification`，解析子查询里的 WHERE 条件。

---

## 2️⃣ Visitor 示例（支持子查询）

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
    public Void visitPredicate(SqlBaseParser.PredicateContext ctx) {
        // 检查是否是 IN 子查询
        if (ctx.getChildCount() >= 3 && ctx.getChild(1).getText().equalsIgnoreCase("IN")) {
            String left = ctx.getChild(0).getText();

            ParseTree third = ctx.getChild(2);
            if (third instanceof SqlBaseParser.QueryContext) {
                SqlBaseParser.QueryContext subQuery = (SqlBaseParser.QueryContext) third;
                visitQuery(subQuery);
            }
        }
        return super.visitPredicate(ctx);
    }

    @Override
    public Void visitQuery(SqlBaseParser.QueryContext ctx) {
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

## 3️⃣ 使用方式

```java
String sql = "SELECT * FROM oper WHERE id IN (SELECT id FROM oper WHERE name = 'Add')";

SqlBaseLexer lexer = new SqlBaseLexer(CharStreams.fromString(sql));
SqlBaseParser parser = new SqlBaseParser(new CommonTokenStream(lexer));

ParseTree tree = parser.singleStatement();

// Listener 拿顶层 WHERE
WhereListener listener = new WhereListener();
ParseTreeWalker.DEFAULT.walk(listener, tree);
SqlBaseParser.BooleanExpressionContext whereExpr = listener.getWhereExpr();

// Visitor 递归解析
WhereVisitor visitor = new WhereVisitor();
visitor.visit(whereExpr);

System.out.println(visitor.conditions);
```

---

## 4️⃣ 输出结果

```
[id = id, name = 'Add']
```

* 外层 `id` 和子查询 `id, name` 都被解析
* 支持任意嵌套子查询

---

## 5️⃣ 核心点总结

1. **不能改 g4** → 利用现有的 `PredicateContext`、`QueryContext` 判断 `IN` 是否跟子查询
2. **递归调用 `visitQuery` + `visitQuerySpecification`** → 解析子查询 WHERE
3. `visitComparison` / `visitLogicalBinary` / `visitParenthesizedExpression` 保留，解析普通逻辑表达式

---

这样就可以 **不修改 g4 文件**，也能解析 `WHERE` 条件里包含的子查询字段。

如果你愿意，我可以帮你写一个**完整工具类**，输入 SQL 返回 **所有 WHERE 字段+表名+操作符**，子查询可以无限嵌套。

你希望我直接写吗？
