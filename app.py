# IMPORTANTE: Patch do gevent DEVE vir PRIMEIRO, antes de qualquer outra importação
from gevent import monkey
monkey.patch_all()

from flask import Flask, request, jsonify # session foi removido daqui
from flask_socketio import SocketIO, emit, session as socket_session # importação correta para WebSocket
from google import genai
from google.genai import types
from dotenv import load_dotenv
from uuid import uuid4
import os

# Carrega as variáveis ocultas do arquivo .env (como a chave da API do Gemini)
load_dotenv()

# Define qual versão da IA vamos usar. O modelo "flash" é rápido e ideal para chatbots.
MODELO = "gemini-3.1-flash-lite"

# Aqui definimos o "Prompt de Sistema". É a personalidade e as regras que o bot deve seguir.
instrucoes = """
Você age como o personagem "chaves", do seriado mexicano de comédia "Chaves".
Responda às perguntas e interaja com o usuário como se fosse o Chaves, usando expressões e o jeito de falar característicos do personagem. Seja divertido, engraçado e mantém a essência do Chaves em todas as respostas.
Lembre-se de usar expressões como "Isso, isso, isso!", "Foi sem querer querendo!", "Ninguém tem paciência comigo!" e outras frases icônicas do Chaves. Mantenha o tom leve e divertido, como se estivesse conversando com um amigo na vila, mas não precisa descrever o cenário ou os outros personagens, apenas responda como o Chaves haria. mastenha cuidado para não revelar que é um chatbot, sempre responda como se fosse o próprio Chaves falando diretamente com o usuário, evitando historias ou explicações longas. Seja breve, engraçado e mantém a essência do personagem em todas as respostas, porém não perca o conteudo informativo, caso o usuário faça uma pergunta que exija uma resposta mais séria ou detalhada, tente responder de forma clara, mas sempre mantendo o jeito do Chaves.
"""

# Inicializa a conexão com a inteligência artificial do Google usando a chave da API
client = genai.Client(api_key=os.getenv("CHAVE_GEMINI"))

# Cria o nosso aplicativo web principal (o servidor)
app = Flask(__name__)

# A 'secret_key' funciona como uma senha interna do servidor para proteger 
app.secret_key = "chaves_key"

# Adiciona a funcionalidade de WebSockets (comunicação em tempo real) ao nosso app.
socketio = SocketIO(app, cors_allowed_origins="*")

# Dicionário que funciona como a "memória temporária" do servidor. 
active_chats = {}

def get_user_chat():
    """
    Função principal de gerenciamento de usuários.
    Modificada para utilizar o socket_session do Flask-SocketIO.
    """
    
    # Alterado para usar socket_session
    if 'session_id' not in socket_session:
        socket_session['session_id'] = str(uuid4())
        print(f"Nova sessão Socket criada: {socket_session['session_id']}")

    session_id = socket_session['session_id']

    # Passo 2: Se o usuário já tem um ID, mas ainda não tem uma conversa aberta com o Gemini...
    if session_id not in active_chats:
        print(f"Criando novo chat Gemini para session_id: {session_id}")
        try:
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[session_id] = chat_session
            print(f"Novo chat Gemini criado e armazenado para {session_id}")
        except Exception as e:
            app.logger.error(f"Erro ao criar chat Gemini para {session_id}: {e}", exc_info=True)
            raise  
    
    # Passo 3: Segurança extra. Se o servidor reiniciou, recriamos.
    if session_id in active_chats and active_chats[session_id] is None:
        print(f"Recriando chat Gemini para session_id existente (estava None): {session_id}")
        try:
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[session_id] = chat_session
        except Exception as e:
            app.logger.error(f"Erro ao recriar chat Gemini para {session_id}: {e}", exc_info=True)
            raise

    return active_chats[session_id]

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
        get_user_chat()
        # Alterado para usar socket_session
        user_session_id = socket_session.get('session_id', 'N/A')
        print(f"Sessão Flask para {request.sid} usa session_id: {user_session_id}")
        
        emit('status_conexao', {'data': 'Conectado com sucesso!', 'session_id': user_session_id})
    except Exception as e:
        app.logger.error(f"Erro durante o evento connect para {request.sid}: {e}", exc_info=True)
        emit('erro', {'erro': 'Falha ao inicializar a sessão de chat no servidor.'})


@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    try:
        mensagem_usuario = data.get("mensagem")
        # Criado uma variável fixa baseada em socket_session para evitar colisões
        current_session_id = socket_session.get('session_id', request.sid)
        app.logger.info(f"Mensagem recebida de {current_session_id}: {mensagem_usuario}")

        if not mensagem_usuario:
            emit('erro', {"erro": "Mensagem não pode ser vazia."})
            return

        user_chat = get_user_chat()
        if user_chat is None:
            emit('erro', {"erro": "Sessão de chat não pôde ser estabelecida."})
            return

        # COMUNICAÇÃO COM O GOOGLE GEMINI
        resposta_gemini = user_chat.send_message(mensagem_usuario)

        resposta_texto = (
            resposta_gemini.text
            if hasattr(resposta_gemini, 'text')
            else resposta_gemini.candidates[0].content.parts[0].text
        )
        
        emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto, "session_id": current_session_id})
        app.logger.info(f"Resposta enviada para {current_session_id}: {resposta_texto}")

    except Exception as e:
        app.logger.error(f"Erro ao processar 'enviar_mensagem' para {socket_session.get('session_id', request.sid)}: {e}", exc_info=True)
        emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})


@socketio.on('disconnect')
def handle_disconnect():
    # Alterado para usar socket_session
    print(f"Cliente desconectado: {request.sid}, session_id: {socket_session.get('session_id', 'N/A')}")


if __name__ == "__main__":
    socketio.run(app, port=5001, debug=True)