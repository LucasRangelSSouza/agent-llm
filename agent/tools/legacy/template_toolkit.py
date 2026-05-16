class CalculatorToolKit:
    """
    Toolkit genérico para operações matemáticas simples.
    Cada subtool representa uma operação.
    """

    def __init__(self):

        self.tool_name="calculator",
        self.system_message="Você é uma calculadora inteligente. Realize cálculos com precisão.",


    # ======================================================
    # Subtool 1️⃣ — Soma
    # ======================================================
    def _add_logic(self, query: str, a: float, b: float) -> str:
        result = a + b
        return f"🧮 Resultado da soma: {a} + {b} = {result}"

    def add_tool(self):
        """Cria a subtool de soma."""
        def _tool(query: str, a: float, b: float):
            return self._add_logic(query=query, a=a, b=b)
        return _tool

    # ======================================================
    # Subtool 2️⃣ — Multiplicação
    # ======================================================
    def _multiply_logic(self, query: str, a: float, b: float) -> str:
        result = a * b
        return f"🧮 Resultado da multiplicação: {a} × {b} = {result}"

    def multiply_tool(self):
        """Cria a subtool de multiplicação."""
        def _tool(query: str, a: float, b: float):
            return self._multiply_logic(query=query, a=a, b=b)
        return _tool

if __name__ == "__main__":
    calc_toolkit = CalculatorToolKit()

    # Criar cada subtool
    add_tool = calc_toolkit.add_tool()
    multiply_tool = calc_toolkit.multiply_tool()

    # Testar
    print(add_tool("somar dois números", 5, 7))
    print(multiply_tool("multiplicar dois números", 4, 3))