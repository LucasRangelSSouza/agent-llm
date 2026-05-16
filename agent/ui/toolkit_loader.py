from agent.infrastructure.runtime.toolkit_registry import iter_enabled_toolkits


def get_toolkits_with_functions():
    """
    Retorna o catalogo declarativo de toolkits.

    A UI nao varre mais arquivos Python. Isso evita toolkits antigos aparecendo
    por acidente e mantem o nome usado no template igual ao nome registrado no
    backend da IA.
    """
    toolkits = {}
    for toolkit in iter_enabled_toolkits():
        toolkit_name = toolkit.get("name")
        if not toolkit_name:
            continue
        functions = [
            function.get("name")
            for function in (toolkit.get("functions") or [])
            if function.get("name")
        ]
        toolkits[toolkit_name] = functions
    return toolkits
