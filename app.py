# IMPORTANTE: Patch do gevent DEVE vir PRIMEIRO, antes de qualquer outra importação
from gevent import monkey
monkey.patch_all()

from flask import Flask, request, jsonify  # Session removido completamente
from flask_socketio import SocketIO, emit   # Apenas o básico e funcional
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os

# Carrega as variáveis ocultas do arquivo .env (como a chave da API do Gemini)
load_dotenv()

# Define qual versão da IA vamos usar. O modelo "flash" é rápido e ideal para chatbots.
MODELO = "gemini-3.1-flash-lite"

# Aqui definimos o "Prompt de Sistema". É a personalidade e as regras que o bot deve seguir.
instrucoes = """
Você age como o personagem "chaves", do seriado mexicano de comédia "Chaves".
Responda às perguntas e interaja com o usuário como se fosse o Chaves, usando expressões e o jeito de falar característicos do personagem. Seja divertido, engraçado e mantém a essência do Chaves em todas as respostas.
Lembre-se de usar expressões como "Isso, isso, isso!", "Foi sem querer querendo!", "Ninguém tem paciência comigo!" e outras frases icônicas do Chaves. Mantenha o tom leve e divertido, como se estivesse conversando com um amigo na vila, mas não precisa descrever o cenário ou os outros personagens, apenas responda como o Chaves faria. mastenha cuidado para não revelar que é um chatbot, sempre responda como se fosse o próprio Chaves falando diretamente com o usuário, evitando historias ou explicações longas. Seja breve, engraçado e mantém a essência do personagem em todas as respostas, porém não perca o conteudo informativo, caso o usuário faça uma pergunta que exija uma resposta mais séria ou detalhada, tente responder de forma clara, mas sempre mantendo o jeito do Chaves.
"""

# Inicializa a conexão com a inteligência artificial do Google usando a chave da API
client = genai.Client(api_key=os.getenv("CHAVE_GEMINI"))

# Cria o nosso aplicativo web principal (o servidor)
app = Flask(__name__)
app.secret_key = "chaves_key"

# Adiciona a funcionalidade de WebSockets ao nosso app.
socketio = SocketIO(app, cors_allowed_origins="*")

# Dicionário que funciona como a "memória temporária" do servidor. 
active_chats = {}

def get_user_chat(sid):
    """
    Função de gerenciamento de usuários baseada no ID único da conexão (request.sid).
    Isso elimina completamente os bugs de escopo e compatibilidade!
    """
    if sid not in active_chats:
        print(f"Criando novo chat Gemini para o cliente (sid): {sid}")
        try:
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[sid] = chat_session
            print(f"Novo chat Gemini criado e armazenado para {sid}")
        except Exception as e:
            app.logger.error(f"Erro ao criar chat Gemini para {sid}: {e}", exc_info=True)
            raise  
    return active_chats[sid]

# Rota simples para verificar se o servidor está rodando.
@app.route('/')
def root():
    return jsonify({
        "api-websocket": "chatbot",
        "status": "ok"
    })


# ------------------------------------------------------------------
# EVENTOS SOCKET.IO
# ------------------------------------------------------------------

@socketio.on('connect')
def handle_connect():
    sid = request.sid  # Identificador único da conexão atual
    print(f"Cliente conectado: {sid}")
    
    try:
        # Inicializa o chat usando o próprio SID do cliente
        get_user_chat(sid)
        emit('status_conexao', {'data': 'Conectado com sucesso!', 'session_id': sid})
    except Exception as e:
        app.logger.error(f"Erro durante o evento connect para {sid}: {e}", exc_info=True)
        emit('erro', {'erro': 'Falha ao inicializar a sessão de chat no servidor.'})


@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    sid = request.sid
    try:
        mensagem_usuario = data.get("mensagem")
        app.logger.info(f"Mensagem recebida de {sid}: {mensagem_usuario}")

        if not mensagem_usuario:
            emit('erro', {"erro": "Mensagem não pode ser vazia."})
            return

        user_chat = get_user_chat(sid)
        if user_chat is None:
            emit('erro', {"erro": "Sessão de chat não pôde ser estabelecida."})
            return

        # Comunicação com o Google Gemini
        resposta_gemini = user_chat.send_message(mensagem_usuario)

        resposta_texto = (
            resposta_gemini.text
            if hasattr(resposta_gemini, 'text')
            else resposta_gemini.candidates[0].content.parts[0].text
        )
        
        emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto, "session_id": sid})
        app.logger.info(f"Resposta enviada para {sid}: {resposta_texto}")

    except Exception as e:
        app.logger.error(f"Erro ao processar 'enviar_mensagem' para {sid}: {e}", exc_info=True)
        emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})


@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"Cliente desconectado: {sid}")
    
    # 🧹 Limpeza de memória: Remove o chat do dicionário para liberar RAM no Render
    if sid in active_chats:
        del active_chats[sid]
        print(f"Memória do chat {sid} liberada com sucesso.")


if __name__ == "__main__":
    socketio.run(app, port=5001, debug=True)