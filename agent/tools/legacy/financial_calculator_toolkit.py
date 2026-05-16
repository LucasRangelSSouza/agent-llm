"""Toolkit para contas financeiras com precisão ajustável."""

import ast
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Callable


class _SafeExpressionEvaluator(ast.NodeVisitor):
    """Avalia expressões aritméticas simples de forma segura."""

    _ALLOWED_BINOPS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Pow: lambda a, b: _SafeExpressionEvaluator._pow_decimal(a, b),
    }

    def evaluate(self, expression: str) -> Decimal:
        tree = ast.parse(expression, mode="eval")
        return self.visit(tree.body)

    def visit_BinOp(self, node: ast.BinOp) -> Decimal:
        left = self.visit(node.left)
        right = self.visit(node.right)
        operator = type(node.op)
        func = self._ALLOWED_BINOPS.get(operator)
        if func is None:
            raise ValueError(f"Operador não suportado: {operator.__name__}")
        return func(left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Decimal:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError("Operador unário não permitido.")

    def visit_Constant(self, node: ast.Constant) -> Decimal:
        value = node.value
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(str(value))
        raise ValueError("Apenas números são permitidos na expressão.")

    def visit_Num(self, node: ast.Num) -> Decimal:  # type: ignore[override]
        return self.visit_Constant(ast.Constant(value=node.n))

    def visit_Name(self, node: ast.Name) -> Decimal:
        raise ValueError(f"Identificador não permitido: {node.id}")

    def generic_visit(self, node: ast.AST) -> Decimal:
        raise ValueError(f"Expressão inválida ou elemento não autorizado: {type(node).__name__}")

    @staticmethod
    def _pow_decimal(base: Decimal, exponent: Decimal) -> Decimal:
        """Suporta potências, funcionando também para expoentes fracionários."""
        try:
            if exponent == exponent.to_integral_value():
                return base.__pow__(int(exponent))
            return Decimal(str(float(base) ** float(exponent)))
        except (InvalidOperation, ValueError) as exc:
            raise InvalidOperation(f"Não foi possível calcular a potência: {exc}") from exc


class FinancialCalculatorToolkit:
    """Toolkit para cálculos financeiros com precisão configurável."""

    def __init__(self, default_precision: int = 5, db_uri=None, **kwargs):
        self.default_precision = default_precision
        self._evaluator = _SafeExpressionEvaluator()

    def calculadora(self) -> Callable[[str, int], str]:
        """Expõe a ferramenta calculadora para o agente."""

        def _tool(expression: str, precision: int | None = None) -> str:
            return self._calculate(expression, precision)

        return _tool

    # --------------------------------------------------
    # Lógica interna
    # --------------------------------------------------
    def _calculate(self, expression: str, precision: int | None) -> str:
        if not expression or not expression.strip():
            return "Erro: expressão vazia. Forneça uma expressão matemática válida."

        precision = self.default_precision if precision is None else precision
        if precision < 0:
            return "Erro: a precisão precisa ser um número inteiro não negativo."

        try:
            with localcontext() as ctx:
                ctx.prec = max(precision, 1) + 8
                value = self._evaluator.evaluate(expression)

            quant = Decimal(1).scaleb(-precision)
            rounded = value.quantize(quant, rounding=ROUND_HALF_UP)

            return (
                f"🧮 Expressão: {expression.strip()}\n"
                f"Resultado: {rounded} (precisão: {precision} casas decimais)"
            )
        except (ValueError, InvalidOperation) as exc:
            return f"Erro no cálculo: {exc}"
