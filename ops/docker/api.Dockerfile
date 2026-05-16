FROM python:3.11-slim@sha256:5be45dbade29bebd6886af6b438fd7e0b4eb7b611f39ba62b430263f82de36d2

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1

# >>> (1) DependÃªncias extras para Prophet/CmdStan
# git Ã© importante porque o cmdstanpy pode precisar e ajuda em builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    poppler-utils \
    tesseract-ocr \
    awscli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Instala Python + dependÃªncias especÃ­ficas
RUN pip install --upgrade pip setuptools wheel && \
pip install -U langsmith autogen openinference-instrumentation-autogen openinference-instrumentation-openai &&\
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-deps -r requirements.txt && \
    pip install packaging && \
    pip install huggingface_hub[hf_xet] && \
    pip install update && \
    pip install langsmith[otel]==0.4.37

# >>> (2) Instalar Prophet + cmdstanpy e instalar o CmdStan
# - prophet precisa de cmdstanpy + cmdstan instalado
# - pin em versÃµes estÃ¡veis para py3.11
RUN pip install --upgrade "cmdstanpy==1.2.2" "prophet==1.1.5" && \
    python - <<'EOF'
import cmdstanpy
cmdstanpy.install_cmdstan(version="2.35.0", verbose=True)
print("CmdStan ok:", cmdstanpy.cmdstan_path())
EOF

# (opcional, mas ajuda) apontar o CMDSTAN explicitamente via ENV
# >>> (3) Exporta o caminho do CmdStan para runtime
ENV CMDSTAN=/root/.cmdstan/cmdstan-2.35.0

RUN python3 - <<'EOF'
from transformers import BlipProcessor, BlipForConditionalGeneration
BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
EOF

COPY . .

RUN find . -type d -name "__pycache__" -exec rm -rf {} + && \
    rm -rf logs/* tmp/* agent/tmp/uploads/* agent/tmp/runtime_logs/* || true && \
    rm -f audit.db || true

EXPOSE 8080

CMD ["uvicorn", "agent_app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

