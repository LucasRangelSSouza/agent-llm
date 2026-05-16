FROM ollama/ollama:latest

COPY free_models/ollama/entrypoint.sh /usr/local/bin/agent-free-llm-entrypoint.sh

RUN chmod +x /usr/local/bin/agent-free-llm-entrypoint.sh

EXPOSE 11434

ENTRYPOINT ["/usr/local/bin/agent-free-llm-entrypoint.sh"]
