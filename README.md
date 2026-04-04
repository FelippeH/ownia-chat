## Ownia

Uma pequena aplicação para um agente conversacional offline. Possui uma interface visual amigável construída no Tkinter, com suporte a um system_prompt que pode ser editado inclusive dentro da própria aplicação e memória simples em memory.json para armazenar conversas localmente.

### Funcionalidades
- `Configuração` permite dar um nome ao agente (obrigatório), definir como o agente te chamará (obrigatório) e opção de adicionar uma imagem para o agente (opcional).
- `Prompt` permite editar o prompt dentro da aplicação
- `Limpar` exclui todo histórico da conversa
- Há também botões/ícones em baixo da última mensagem enviada pelo agente, que permite: `gerar uma nova resposta` (substituindo a última mensagem enviada), `editar resposta` (você pode editar a resposta do agente caso queira), `excluir mensagem` (exclui a última mensagem, essa opção também está disponível para as suas próprias mensagens) e `continuar conversa` (o agente envia uma nova mensagem sem excluir a anterior).

  
![0](https://github.com/user-attachments/assets/c7405f79-b279-4df9-bb64-645a159e4b19)



### Requisitos

- Ollama
  - Será necessário baixar o modelo que for usar na aplicação, por padrão eu deixei o `mistral`.
  - Caso queira usar outro modelo, execute: ollama pull `nome do modelo`.
  - Depois basta alterar o modelo usado em "model" na linha 121 do gui.py.
- Python 3.10+
- Pip
- Dependências listadas em requirements.txt (pillow, requests e pyinstaller)

### Instalação (desenvolvimento)

- Criar e ativar o ambiente virtual:
   - python -m venv .venv
   - venv\Scripts\activate
- Instalar dependências:
   - pip install -r requirements.txt

### Executando localmente

Recomenmdo executar diretamente usando `python gui.py`, ou executando o gui.exe (nesse caso será necessário gerar um novo executável para cada alteração feita no script).

Para gerar um novo executável: `pyinstaller --onefile --noconsole --distpath . gui.py`

### Editando o prompt do sistema

- O prompt pode ser editado via interface da aplicação ou diretamente no system_prompt.txt
