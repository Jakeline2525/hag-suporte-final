# app.py (Com a correção do TemplateNotFound)

import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, join_room, send
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

load_dotenv()

# --- CORREÇÃO APLICADA AQUI ---
# Dizemos explicitamente ao Flask onde encontrar a pasta de templates.
app = Flask(__name__, template_folder='templates')

# --- O RESTO DO ARQUIVO CONTINUA IGUAL ---
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'uma-chave-secreta-padrao-para-desenvolvimento')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode='eventlet')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça login para acessar esta página."
login_manager.login_message_category = "warning"

# ... (O resto do seu código continua aqui, sem nenhuma outra alteração)
# ... (Cole o restante do seu app.py original aqui)
# --- MODELOS DO BANCO DE DADOS ---
class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    def set_password(self, password): self.senha_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.senha_hash, password)

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    protocolo = db.Column(db.String(25), unique=True, nullable=False)
    nome_cliente = db.Column(db.String(100), nullable=False)
    email_cliente = db.Column(db.String(100), nullable=False)
    setor = db.Column(db.String(50), nullable=False)
    funcao = db.Column(db.String(50), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    anexo = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(30), nullable=False, default='Aguardando Resposta')
    data_criacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    mensagens = db.relationship('Mensagem', backref='ticket', lazy=True)

class Mensagem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conteudo = db.Column(db.Text, nullable=False)
    autor = db.Column(db.String(100), nullable=False)
    data_envio = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# --- FUNÇÃO DE ENVIO DE E-MAIL ---
def enviar_email_notificacao(protocolo, email_destinatario, status, dados_ticket=None):
    base_url = os.getenv('BASE_URL', 'http://127.0.0.1:5000' )
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 465
    EMAIL_REMETENTE = os.getenv('EMAIL_USER')
    SENHA_REMETENTE = os.getenv('EMAIL_PASS')

    if not all([EMAIL_REMETENTE, SENHA_REMETENTE]):
        print("!!! AVISO: Credenciais de e-mail não configuradas no .env. E-mail não será enviado.")
        return

    assunto = f"Atualização do seu Ticket: {protocolo}"
    corpo_html = f"""
    <html><body style="font-family: sans-serif; background-color: #f4f4f4; padding: 20px;">
        <div style="max-width: 600px; margin: auto; background-color: #ffffff; padding: 20px; border-radius: 8px;">
            <h2 style="color: #333;">Atualização do Ticket de Suporte HAG</h2>
            <p><strong>Protocolo:</strong> {protocolo}</p>
            <p><strong>Novo Status:</strong> <span style="font-weight: bold; color: #00AEEF;">{status}</span></p>
            <p>Você pode acompanhar seu ticket e conversar com o suporte acessando o link abaixo:</p>
            <a href="{base_url}/chat/{protocolo}" style="display: inline-block; padding: 10px 20px; background-color: #00AEEF; color: #ffffff; text-decoration: none; border-radius: 5px;">Acessar Ticket</a>
        </div>
    </body></html>
    """
    if status == "Novo Ticket Aberto":
        assunto = f"Novo Ticket Aberto: {protocolo}"
        corpo_html = f"""
        <html><body style="font-family: sans-serif; background-color: #f4f4f4; padding: 20px;">
            <div style="max-width: 600px; margin: auto; background-color: #ffffff; padding: 20px; border-radius: 8px;">
                <h2 style="color: #333;">Novo Ticket de Suporte Recebido</h2>
                <p><strong>Protocolo:</strong> {protocolo}</p>
                <p>Um novo ticket foi aberto por <strong>{dados_ticket['nome_cliente']}</strong>.</p>
                <p>Para visualizar os detalhes e iniciar o chat, acesse o dashboard:</p>
                <a href="{base_url}/login" style="display: inline-block; padding: 10px 20px; background-color: #00AEEF; color: #ffffff; text-decoration: none; border-radius: 5px;">Acessar Sistema</a>
            </div>
        </body></html>
        """

    msg = MIMEMultipart()
    msg['From'] = f"Suporte HAG <{EMAIL_REMETENTE}>"
    msg['To'] = email_destinatario
    msg['Subject'] = assunto
    msg.attach(MIMEText(corpo_html, 'html'))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
            server.sendmail(EMAIL_REMETENTE, email_destinatario, msg.as_string())
        print(f"E-mail de notificação ('{status}') enviado para {email_destinatario}")
    except Exception as e:
        print(f"!!!!!!!!!! ERRO AO ENVIAR E-MAIL PARA {email_destinatario} !!!!!!!!!!\nErro: {e}")

# --- ROTAS PÚBLICAS ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        protocolo = f"TICKET-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        caminho_anexo_salvo = None
        if 'anexo' in request.files:
            arquivo = request.files['anexo']
            if arquivo.filename != '':
                filename = secure_filename(protocolo + "_" + arquivo.filename)
                caminho_anexo_salvo = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                arquivo.save(caminho_anexo_salvo)
        novo_ticket = Ticket(protocolo=protocolo, nome_cliente=request.form['nome'], email_cliente=request.form['email'], setor=request.form['setor'], funcao=request.form['funcao'], descricao=request.form['descricao'], anexo=caminho_anexo_salvo, status='Aguardando Resposta')
        db.session.add(novo_ticket)
        db.session.commit()
        enviar_email_notificacao(protocolo, novo_ticket.email_cliente, novo_ticket.status)
        enviar_email_notificacao(protocolo, 'jakelinesouza@hagmachado.com.br', 'Novo Ticket Aberto', dados_ticket={'nome_cliente': novo_ticket.nome_cliente})
        session['protocolo'] = protocolo
        session['nome_usuario'] = novo_ticket.nome_cliente
        return redirect(url_for('ticket_criado', protocolo=protocolo))
    return render_template('index.html')

@app.route('/ticket-criado/<protocolo>')
def ticket_criado(protocolo):
    return render_template('ticket_criado.html', protocolo=protocolo)

# --- ROTAS DE AUTENTICAÇÃO ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and usuario.check_password(senha):
            login_user(usuario)
            return redirect(url_for('dashboard'))
        else:
            flash('E-mail ou senha inválidos. Tente novamente.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você foi desconectado com sucesso.', 'success')
    return redirect(url_for('login'))

@app.route('/registrar', methods=['GET', 'POST'])
@login_required
def registrar():
    if not current_user.is_admin:
        flash('Você não tem permissão para realizar esta ação.', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']
        usuario_existente = Usuario.query.filter_by(email=email).first()
        if usuario_existente:
            flash('Este e-mail já está cadastrado.', 'warning')
            return redirect(url_for('registrar'))
        novo_usuario = Usuario(nome=nome, email=email)
        novo_usuario.set_password(senha)
        db.session.add(novo_usuario)
        db.session.commit()
        flash(f'Usuário {nome} criado com sucesso!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('registrar.html')

# --- ROTAS PROTEGIDAS (GERENCIAMENTO) ---
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
    novo_status = request.form.get('novo_status')
    comentario = request.form.get('comentario')
    if novo_status and ticket.status != novo_status:
        ticket.status = novo_status
        flash(f'Status do ticket alterado para "{novo_status}".', 'success')
        enviar_email_notificacao(ticket.protocolo, ticket.email_cliente, novo_status)
    if comentario:
        nova_mensagem = Mensagem(conteudo=f"[COMENTÁRIO INTERNO] {comentario}", autor=current_user.nome, ticket_id=ticket.id)
        db.session.add(nova_mensagem)
        flash('Comentário adicionado com sucesso.', 'success')
    db.session.commit()
    return redirect(url_for('ticket_detalhes', protocolo=protocolo))

@app.route('/chat/<protocolo>')
def chat(protocolo):
    ticket = Ticket.query.filter_by(protocolo=protocolo).first_or_404()
    if current_user.is_authenticated:
        nome_usuario = current_user.nome
    else:
        nome_usuario = session.get('nome_usuario', 'Cliente')
    return render_template('chat.html', protocolo=protocolo, nome_usuario=nome_usuario, historico=ticket.mensagens)

# --- EVENTOS DO SOCKET.IO ---
@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    send({'msg': f'{username} entrou no chat.', 'is_system': True}, to=room)

@socketio.on('message')
def on_message(data):
    room = data['room']
    ticket = Ticket.query.filter_by(protocolo=room).first()
    if ticket:
        nova_mensagem = Mensagem(conteudo=data['msg'], autor=data['username'], ticket_id=ticket.id)
        db.session.add(nova_mensagem)
        db.session.commit()
    send(data, to=room, broadcast=True)

# --- EXECUÇÃO ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Usuario.query.first():
            print("Criando primeiro usuário administrador...")
            admin = Usuario(nome='Admin HAG', email='jakelinesouza@hagmachado.com.br', is_admin=True)
            admin.set_password('Templo@25')
            db.session.add(admin)
            db.session.commit()
            print("Usuário administrador criado com sucesso.")
    socketio.run(app, debug=True)
