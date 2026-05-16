import ast
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any, Optional


class _SafeDecimalEvaluator(ast.NodeVisitor):
    _ALLOWED_BINOPS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Pow: lambda a, b: _SafeDecimalEvaluator._pow(a, b),
        ast.Mod: lambda a, b: a % b,
    }

    def evaluate(self, expression: str) -> Decimal:
        tree = ast.parse(expression, mode="eval")
        return self.visit(tree.body)

    def visit_BinOp(self, node: ast.BinOp) -> Decimal:
        left = self.visit(node.left)
        right = self.visit(node.right)
        handler = self._ALLOWED_BINOPS.get(type(node.op))
        if handler is None:
            raise ValueError(f"Operador nao suportado: {type(node.op).__name__}")
        return handler(left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Decimal:
        value = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        raise ValueError("Operador unario nao permitido.")

    def visit_Constant(self, node: ast.Constant) -> Decimal:
        value = node.value
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(str(value))
        raise ValueError("Apenas numeros sao permitidos.")

    def visit_Num(self, node: ast.Num) -> Decimal:  # type: ignore[override]
        return self.visit_Constant(ast.Constant(value=node.n))

    def generic_visit(self, node: ast.AST) -> Decimal:
        raise ValueError(f"Expressao invalida: {type(node).__name__}")

    @staticmethod
    def _pow(base: Decimal, exponent: Decimal) -> Decimal:
        if exponent == exponent.to_integral_value():
            return base ** int(exponent)
        return Decimal(str(float(base) ** float(exponent)))


class CalculatorToolkit:
    """Calculadora decimal segura para contas deterministicas."""

    def __init__(self, default_precision: int = 4, **_: Any) -> None:
        self.default_precision = default_precision
        self.evaluator = _SafeDecimalEvaluator()

    def calculate(self):
        def _tool(expression: str, precision: Optional[int] = None) -> str:
            try:
                clean_expression = (expression or "").strip()
                if not clean_expression:
                    raise ValueError("Campo expression e obrigatorio.")

                digits = self.default_precision if precision is None else int(precision)
                if digits < 0:
                    raise ValueError("precision precisa ser maior ou igual a zero.")

                with localcontext() as ctx:
                    ctx.prec = max(digits, 1) + 12
                    value = self.evaluator.evaluate(clean_expression)

                quant = Decimal(1).scaleb(-digits)
                rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
                payload = {
                    "success": True,
                    "expression": clean_expression,
                    "precision": digits,
                    "result": str(rounded),
                    "text": f"Resultado: {rounded} (precisao: {digits} casas decimais)",
                }
            except (ValueError, InvalidOperation, ZeroDivisionError) as exc:
                payload = {"success": False, "error": str(exc)}

            return json.dumps(payload, ensure_ascii=False)

        return _tool
