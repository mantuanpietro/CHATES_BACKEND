# IMPORTANTE: Patch do gevent DEVE vir PRIMEIRO, antes de qualquer outra importação
from gevent import monkey
monkey.patch_all()

from flask import Flask, request, jsonify  # Removido o session do Flask completamente
from flask_socketio import SocketIO, emit, save_session, get_session # Ferramentas nativas do SocketIO
from google import genai
from google.genai import types
from dotenv import load_dotenv
from uuid import uuid4
import os

# Carrega as variáveis ocultas do arquivo .env (como a chave da API do Gemini)
load_dotenv()

# Define qual versão da IA vamos usar. O modelo "flash" é rápido e ideal para chatbots.
MODELO = "gemini-3.1-flash-lite"

# Aqui definimos o "Prompt de Sistema".
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

# Inicializa o SocketIO normal
socketio = SocketIO(app, cors_allowed_origins="*")

# Dicionário que funciona como a "memória temporária" do servidor. 
active_chats = {}

def obter_ou_criar_sessao():
    """
    Função auxiliar para ler ou criar o session_id usando os métodos nativos do Flask-SocketIO.
    """
    sid = request.sid
    # Tenta buscar a sessão existente desse cliente específico (sid)
    with get_session(sid) as s:
        if 'session_id' not in s:
            s['session_id'] = str(uuid4())
            save_session(sid, s)
            print(f"Nova sessão SocketIO criada para {sid}: {s['session_id']}")
        return s['session_id']

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
    print(f"Cliente conectado: {request.sid}")
    
    try:
        # Garante a criação do session_id via SocketIO
        session_id = obter_ou_criar_sessao()
        print(f"Sessão para {request.sid} usa session_id: {session_id}")
        
        # Se ainda não tem chat criado no active_chats para esse ID, cria um novo
        if session_id not in active_chats:
            print(f"Criando novo chat Gemini para session_id: {session_id}")
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[session_id] = chat_session

        emit('status_conexao', {'data': 'Conectado com sucesso!', 'session_id': session_id})
    except Exception as e:
        app.logger.error(f"Erro durante o evento connect para {request.sid}: {e}", exc_info=True)
        emit('erro', {'erro': 'Falha ao inicializar a sessão de chat no servidor.'})


@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    try:
        mensagem_usuario = data.get("mensagem")
        
        # Recupera o session_id correto de forma segura
        session_id = obter_ou_criar_sessao()
        app.logger.info(f"Mensagem recebida de {session_id}: {mensagem_usuario}")

        if not mensagem_usuario:
            emit('erro', {"erro": "Mensagem não pode ser vazia."})
            return

        # Busca o chat correspondente
        user_chat = active_chats.get(session_id)
        
        # Caso o servidor tenha reiniciado e limpado o active_chats, recria o chat aqui
        if user_chat is None:
            print(f"Recriando chat Gemini perdido para session_id: {session_id}")
            user_chat = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[session_id] = user_chat

        # Comunicação com o Gemini
        resposta_gemini = user_chat.send_message(mensagem_usuario)

        resposta_texto = (
            resposta_gemini.text
            if hasattr(resposta_gemini, 'text')
            else resposta_gemini.candidates[0].content.parts[0].text
        )
        
        emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto, "session_id": session_id})
        app.logger.info(f"Resposta enviada para {session_id}: {resposta_texto}")

    except Exception as e:
        app.logger.error(f"Erro ao processar 'enviar_mensagem': {e}", exc_info=True)
        emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})


@socketio.on('disconnect')
def handle_disconnect():
    session_id = obter_ou_criar_sessao()
    print(f"Cliente desconectado: {request.sid}, session_id: {session_id}")


if __name__ == "__main__":
    socketio.run(app, port=5001, debug=True)