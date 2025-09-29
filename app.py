# aplicativo.py

# --- CORREÇÃO DE ORDEM: EVENTLET NO TOPO ABSOLUTO ---
# Esta é a primeira coisa que o programa executa, garantindo que todas as
# bibliotecas subsequentes sejam compatíveis com o servidor assíncrono.
import eventlet
eventlet.monkey_patch()
# --- FIM DA CORREÇÃO ---

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import secrets # Para gerar SECRET_KEY se não estiver no .env

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- CONFIGURAÇÃO DA APLICAÇÃO FLASK ---
app = Flask(__name__, template_folder='templates')

# Configurações da aplicação
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(16))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///suporte.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicialização das extensões
db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode='eventlet')
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça login para acessar esta página."
login_manager.login_message_category = "warning"

# --- MODELOS DO BANCO DE DADOS (SQLAlchemy) ---

class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    protocolo = db.Column(db.String(20), unique=True, nullable=False)
    nome_cliente = db.Column(db.String(100), nullable=False)
    email_cliente = db.Column(db.String(100), nullable=False)
    setor = db.Column(db.String(50))
    funcao = db.Column(db.String(50))
    descricao = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default='Aguardando Resposta')
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    anexo = db.Column(db.String(200), nullable=True) # Mesmo desativado, o campo existe

class Mensagem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_protocolo = db.Column(db.String(20), db.ForeignKey('ticket.protocolo'), nullable=False)
    autor = db.Column(db.String(100), nullable=False)
    conteudo = db.Column(db.Text, nullable=False)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)
    is_system_message = db.Column(db.Boolean, default=False)

# --- COMANDOS DO FLASK (para criar o banco de dados) ---

@app.cli.command('create-db')
def create_db():
    """Cria as tabelas do banco de dados e o usuário admin."""
    with app.app_context():
        db.create_all()
        print("Banco de dados criado.")
        # Cria usuário admin se não existir
        if not Usuario.query.filter_by(email='jakelinesouza@hagmachado.com.br').first():
            admin = Usuario(
                nome='Jakeline Souza (Admin)',
                email='jakelinesouza@hagmachado.com.br',
                is_admin=True
            )
            admin.set_senha('Templo@25')
            db.session.add(admin)
            db.session.commit()
            print("Usuário administrador criado com sucesso.")

# --- FUNÇÕES AUXILIARES ---

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

def enviar_email_notificacao(ticket, tipo='abertura'):
    """Envia e-mail de notificação para cliente e suporte."""
    # Configurações de e-mail
    EMAIL_USER = os.getenv('EMAIL_USER')
    EMAIL_PASS = os.getenv('EMAIL_PASS')
    BASE_URL = os.getenv('BASE_URL', 'http://127.0.0.1:5000' )

    if not EMAIL_USER or not EMAIL_PASS:
        print("AVISO: Credenciais de e-mail não configuradas. E-mail não enviado.")
        return

    # Lista de destinatários
    destinatarios = ['jakelinesouza@hagmachado.com.br', ticket.email_cliente]
    
    # Assunto e corpo do e-mail
    if tipo == 'abertura':
        assunto = f"Novo Ticket Aberto: {ticket.protocolo}"
        corpo = f"""
        <h2>Novo Ticket de Suporte Registrado</h2>
        <p>Olá,</p>
        <p>Um novo ticket foi aberto com as seguintes informações:</p>
        <ul>
            <li><strong>Protocolo:</strong> {ticket.protocolo}</li>
            <li><strong>Nome:</strong> {ticket.nome_cliente}</li>
            <li><strong>E-mail:</strong> {ticket.email_cliente}</li>
            <li><strong>Setor:</strong> {ticket.setor}</li>
            <li><strong>Função:</strong> {ticket.funcao}</li>
            <li><strong>Status:</strong> {ticket.status}</li>
        </ul>
        <h3>Descrição do Problema:</h3>
        <p>{ticket.descricao}</p>
        <p>Para acompanhar, acesse o sistema.</p>
        """
    else: # Atualização de status
        assunto = f"Atualização no Ticket: {ticket.protocolo}"
        corpo = f"""
        <h2>Atualização no seu Ticket</h2>
        <p>Olá {ticket.nome_cliente},</p>
        <p>O status do seu ticket <strong>{ticket.protocolo}</strong> foi atualizado para: <strong>{ticket.status}</strong>.</p>
        <p>Para acompanhar ou falar com o suporte, acesse o sistema.</p>
        """

    # Envio do e-mail
    for destinatario in destinatarios:
        try:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_USER
            msg['To'] = destinatario
            msg['Subject'] = assunto
            msg.attach(MIMEText(corpo, 'html'))

            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(EMAIL_USER, EMAIL_PASS)
                server.send_message(msg)
            print(f"E-mail enviado com sucesso para {destinatario}")
        except Exception as e:
            print(f"Falha ao enviar e-mail para {destinatario}: {e}")

# --- ROTAS DA APLICAÇÃO (Páginas) ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        protocolo = f"TICKET-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        novo_ticket = Ticket(
            protocolo=protocolo,
            nome_cliente=request.form['nome'],
            email_cliente=request.form['email'],
            setor=request.form['setor'],
            funcao=request.form['funcao'],
            descricao=request.form['descricao'],
            status='Aguardando Resposta'
        )
        
        # Lógica de upload desativada para o plano gratuito
        # anexo = request.files.get('anexo')
        # if anexo and anexo.filename != '':
        #     nome_seguro = secure_filename(anexo.filename)
        #     caminho_anexo = os.path.join('uploads', nome_seguro)
        #     # anexo.save(caminho_anexo) # Operação de escrita em disco desativada
        #     novo_ticket.anexo = nome_seguro

        db.session.add(novo_ticket)
        db.session.commit()

        # --- CORREÇÃO: E-MAIL REATIVADO ---
        enviar_email_notificacao(novo_ticket, tipo='abertura')
        
        return redirect(url_for('ticket_criado', protocolo=protocolo))
        
    return render_template('index.html')

@app.route('/ticket_criado/<protocolo>')
def ticket_criado(protocolo):
    return render_template('ticket_criado.html', protocolo=protocolo)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and usuario.check_senha(senha):
            login_user(usuario)
            return redirect(url_for('dashboard'))
        else:
            flash('E-mail ou senha inválidos.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/registrar', methods=['GET', 'POST'])
@login_required
def registrar():
    if not current_user.is_admin:
        flash('Acesso negado. Apenas administradores podem registrar novos usuários.', 'danger')
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']
        is_admin = 'is_admin' in request.form
        
        if Usuario.query.filter_by(email=email).first():
            flash('Este e-mail já está em uso.', 'warning')
            return redirect(url_for('registrar'))
            
        novo_usuario = Usuario(nome=nome, email=email, is_admin=is_admin)
        novo_usuario.set_senha(senha)
        db.session.add(novo_usuario)
        db.session.commit()
        
        flash('Novo usuário criado com sucesso!', 'success')
        return redirect(url_for('dashboard'))
        
    return render_template('registrar.html')

@app.route('/dashboard')
@login_required
def dashboard():
    tickets = Ticket.query.order_by(Ticket.data_criacao.desc()).all()
    return render_template('dashboard.html', tickets=tickets)

@app.route('/ticket/<protocolo>')
@login_required
def ticket_detalhes(protocolo):
    ticket = Ticket.query.filter_by(protocolo=protocolo).first_or_404()
    return render_template('ticket_detalhes.html', ticket=ticket)

@app.route('/ticket/<protocolo>/atualizar', methods=['POST'])
@login_required
def atualizar_ticket(protocolo):
    ticket = Ticket.query.filter_by(protocolo=protocolo).first_or_404()
    novo_status = request.form['novo_status']
    comentario = request.form.get('comentario')

    # Atualiza o status
    if ticket.status != novo_status:
        ticket.status = novo_status
        # --- CORREÇÃO: E-MAIL REATIVADO ---
        enviar_email_notificacao(ticket, tipo='atualizacao')
        
        # Salva a mudança de status como uma mensagem de sistema no chat
        msg_status = Mensagem(
            ticket_protocolo=protocolo,
            autor=current_user.nome,
            conteudo=f"Status alterado para: {novo_status}",
            is_system_message=True
        )
        db.session.add(msg_status)

    # Adiciona comentário interno se houver
    if comentario:
        msg_comentario = Mensagem(
            ticket_protocolo=protocolo,
            autor=current_user.nome,
            conteudo=f"Comentário interno: {comentario}",
            is_system_message=True
        )
        db.session.add(msg_comentario)

    db.session.commit()
    flash('Ticket atualizado com sucesso!', 'success')
    return redirect(url_for('ticket_detalhes', protocolo=protocolo))

@app.route('/chat/<protocolo>')
def chat(protocolo):
    ticket = Ticket.query.filter_by(protocolo=protocolo).first_or_404()
    historico = Mensagem.query.filter_by(ticket_protocolo=protocolo).order_by(Mensagem.data_envio).all()
    
    nome_usuario = current_user.nome if current_user.is_authenticated else ticket.nome_cliente
    session['nome_usuario'] = nome_usuario
    
    return render_template('chat.html', protocolo=protocolo, historico=historico, nome_usuario=nome_usuario)

# --- LÓGICA DO CHAT (Socket.IO) ---

@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    emit('message', {'msg': f'{username} entrou no chat.', 'username': 'Sistema', 'is_system': True}, to=room)

@socketio.on('message')
def handle_message(data):
    room = data['room']
    
    # Salva a mensagem no banco de dados
    nova_mensagem = Mensagem(
        ticket_protocolo=room,
        autor=data['username'],
        conteudo=data['msg']
    )
    db.session.add(nova_mensagem)
    db.session.commit()
    
    emit('message', data, to=room)

# --- EXECUÇÃO DA APLICAÇÃO ---
if __name__ == '__main__':
    socketio.run(app, debug=True)

