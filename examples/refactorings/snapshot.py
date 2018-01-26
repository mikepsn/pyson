import javalang
import javalang.tree
import collections
import glob2
import sys


def merge_declaration(decl, scope):
    for declarator in decl.declarators:
        scope[declarator.name] = decl.type.name


class Visitor:
    def walk_compilation_unit(self, unit):
        for decl in unit.types:
            if isinstance(decl, javalang.tree.ClassDeclaration):
                self.walk_klass(decl)

    def visit_klass(self, klass):
        print("class(\"%s\")." % klass.name)

    def visit_method(self, klass, method):
        print("method(\"%s\", \"%s\", %d, %d)." % (klass.name, method.name, loc(method), complexity(method)))

    def visit_calls(self, klass, method, qualifier, member):
        print("calls(\"%s\", \"%s\", \"%s\", \"%s\")." % (
            klass.name, method.name, qualifier, member))

    def walk_klass(self, klass):
        self.visit_klass(klass)

        scope = {}

        for field in klass.fields:
            merge_declaration(field, scope)

        for method in klass.methods:
            self.walk_method(klass, method, scope)

    def walk_method(self, klass, method, scope):
        self.visit_method(klass, method)

        arg_scope = {}
        for parameter in method.parameters:
            arg_scope[parameter.name] = parameter.type.name

        scope = collections.ChainMap(arg_scope, scope)

        if method.body:
            self.walk_block(klass, method, method.body, scope)

    def walk_block(self, klass, method, stmts, scope):
        scope = collections.ChainMap({}, scope)
        for stmt in stmts:
            self.walk_statement(klass, method, stmt, scope)

    def walk_statement(self, klass, method, stmt, scope):
        if isinstance(stmt, javalang.tree.StatementExpression):
            self.walk_expression(klass, method, stmt.expression, scope)
        elif isinstance(stmt, javalang.tree.IfStatement):
            self.walk_expression(klass, method, stmt.condition, scope)
            self.walk_statement(klass, method, stmt.then_statement, scope)
            if stmt.else_statement:
                self.walk_statement(klass, method, stmt.else_statement, scope)
        elif isinstance(stmt, javalang.tree.VariableDeclaration):
            merge_declaration(stmt, scope)
        elif isinstance(stmt, javalang.tree.BlockStatement):
            self.walk_block(klass, method, stmt.statements, scope)
        elif isinstance(stmt, (javalang.tree.ReturnStatement, javalang.tree.ThrowStatement)):
            self.walk_expression(klass, method, stmt.expression, scope)
        elif isinstance(stmt, (javalang.tree.WhileStatement, javalang.tree.DoStatement)):
            self.walk_expression(klass, method, stmt.condition, scope)
            self.walk_statement(klass, method, stmt.body, scope)
        elif isinstance(stmt, javalang.tree.ForStatement):
            s = collections.ChainMap({}, scope)
            if isinstance(stmt.control, javalang.tree.ForControl):
                if stmt.control.init:
                    merge_declaration(stmt.control.init, s)
            else:
                merge_declaration(stmt.control.var, s)
            self.walk_statement(klass, method, stmt.body, s)
        elif isinstance(stmt, (javalang.tree.BreakStatement, javalang.tree.ContinueStatement)):
            pass
        elif isinstance(stmt, javalang.tree.SynchronizedStatement):
            self.walk_block(klass, method, stmt.block, scope)
        elif isinstance(stmt, javalang.tree.TryStatement):
            if stmt.block:
                self.walk_block(klass, method, stmt.block, scope)
            if stmt.catches:
                for catch in stmt.catches:
                    # Latest Java can catch multiple exception types in one
                    # statement
                    #assert len(catch.parameter.types) == 1
                    s = collections.ChainMap({}, scope)
                    s[catch.parameter.name] = catch.parameter.types[0]
                    self.walk_block(klass, method, catch.block, s)
            if stmt.finally_block:
                self.walk_block(klass, method, stmt.finally_block, scope)
        elif isinstance(stmt, javalang.tree.SwitchStatement):
            self.walk_expression(klass, method, stmt.expression, scope)
            for case in stmt.cases:
                self.walk_block(klass, method, case.statements, scope)
        elif isinstance(stmt, javalang.tree.Statement):
            pass  # lone semicolon
        else:
            raise RuntimeError("unknown stmt %s" % stmt)

    def walk_expression(self, klass, method, expression, scope):
        if isinstance(expression, javalang.tree.MethodInvocation):
            if not expression.qualifier:
                qualifier = klass.name
            elif expression.qualifier[0].islower():
                qualifier = scope.get(expression.qualifier, expression.qualifier)
            else:
                qualifier = expression.qualifier

            self.visit_calls(klass, method, qualifier, expression.member)


def loc(node):
    if isinstance(node, javalang.tree.MethodDeclaration):
        if node.body:
            return 2 + sum(loc(stmt) for stmt in node.body)
        else:
            return 1
    elif isinstance(node, javalang.tree.IfStatement):
        s = 2
        if node.then_statement:
            s += loc(node.then_statement)
        if node.else_statement:
            s += loc(node.else_statement) + 1
        return s
    elif isinstance(node, javalang.tree.BlockStatement):
        return sum(loc(stmt) for stmt in node.statements)
    elif isinstance(node, javalang.tree.TryStatement):
        s = 1
        if node.block:
            s += sum(loc(stmt) for stmt in node.block)
        if node.catches:
            for catch in node.catches:
                s += 1 + sum(loc(stmt) for stmt in catch.block)
        if node.finally_block:
            s += 1 + sum(loc(stmt) for stmt in node.finally_block)
        return s
    elif isinstance(node, javalang.tree.SwitchStatement):
        s = 2
        for case in node.cases:
            s += 1 + sum(loc(stmt) for stmt in case.statements)
        return s
    elif isinstance(node, (javalang.tree.ForStatement,
                           javalang.tree.WhileStatement,
                           javalang.tree.DoStatement)):
        return 1 + loc(node.body)
    elif isinstance(node, javalang.tree.SynchronizedStatement):
        return 2 + sum(loc(stmt) for stmt in node.block)
    elif isinstance(node, (javalang.tree.ReturnStatement,
                           javalang.tree.StatementExpression,
                           javalang.tree.ThrowStatement,
                           javalang.tree.LocalVariableDeclaration,
                           javalang.tree.BreakStatement,
                           javalang.tree.ContinueStatement)):
        return 1
    elif isinstance(node, javalang.tree.Statement):
        return 0  # lone semicolon
    else:
        raise RuntimeError("can not count loc of %s" % (node, ))


def complexity(node):
    # evaluated recursively, so that the value for the method
    # is the actual cyclomatic complexity.
    if isinstance(node, javalang.tree.MethodDeclaration):
        c = 1
        if node.body:
            c += sum(complexity(stmt) for stmt in node.body)
        return c
    elif isinstance(node, javalang.tree.IfStatement):
        c = 1
        if node.then_statement:
            c += complexity(node.then_statement)
        if node.else_statement:
            c += complexity(node.else_statement)
        return c
    elif isinstance(node, javalang.tree.BlockStatement):
        return sum(complexity(stmt) for stmt in node.statements)
    elif isinstance(node, javalang.tree.TryStatement):
        c = 0
        if node.block:
            c += sum(complexity(stmt) for stmt in node.block)
        if node.catches:
            for catch in node.catches:
                c += 1 + sum(complexity(stmt) for stmt in catch.block)
        if node.finally_block:
            c += sum(complexity(stmt) for stmt in node.finally_block)
        return c
    elif isinstance(node, javalang.tree.SwitchStatement):
        c = 0
        for case in node.cases:
            c += sum(complexity(stmt) for stmt in case.statements)
        return c
    elif isinstance(node, (javalang.tree.ForStatement,
                           javalang.tree.WhileStatement,
                           javalang.tree.DoStatement)):
        return 1 + complexity(node.body)
    elif isinstance(node, javalang.tree.SynchronizedStatement):
        return sum(complexity(stmt) for stmt in node.block)
    else:
        return 0


if __name__ == "__main__":
    #for src in glob2.glob(sys.argv[1] + "/src/main/**/*.java"):
    visitor = Visitor()
    for src in glob2.glob(sys.argv[1] + "/src/**/*.java"):
        print()
        print("#", src)
        print()
        with open(src) as f:
            visitor.walk_compilation_unit(javalang.parse.parse(f.read()))
