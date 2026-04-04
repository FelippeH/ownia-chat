# Ownia

Uma pequena aplicação para um agente conversacional local. Fornece uma interface gráfica em Tkinter que envia prompts para um LLM (via Ollama/HTTP) e exibe respostas, com suporte a um system_prompt que pode ser editado inclusive dentro da própria aplicação e memória simples em memory.json para armazenar conversas localmente.

## Requisitos

- Ollama
  Será necessário baixar o modelo que for usar na aplicação, por padrão eu deixei o `mistral`.
  Caso queira usar outro modelo, execute: ollama pull `nome do modelo`.
  Depois basta alterar o modelo usado em "model" na linha 121 do gui.py.
- Python 3.10+
- Pip
- Dependências listadas em requirements.txt (pillow, requests e pyinstaller)

## Instalação (desenvolvimento)

1. Criar e ativar o ambiente virtual:
   - python -m venv .venv
   - venv\Scripts\activate
2. Instalar dependências:
   - pip install -r requirements.txt

## Executando localmente

Recomenmdo executar diretamente usando python gui.py, ou executando o gui.exe (nesse caso será necessário gerar um novo executável para cada alteração feita no código).

Para gerar um novo executável: pyinstaller --onefile --noconsole --distpath . gui.py

## Editando o prompt do sistema

- O prompt pode ser editado via interface da aplicação ou diretamente no system_prompt.txt

## Sobre `memory.json`

- O projeto contém `memory.json` como arquivo seed (vazio) para facilitar a execução inicial. Ele armazena preferências e histórico local.
