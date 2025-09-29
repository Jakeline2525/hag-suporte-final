# aplicativo.py (versão final com SendGrid)

import eventlet
eventlet.monkey_patch()

import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import secrets
# --- NOVA IMPORTAÇÃO PARA O SENDGRID ---
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
# --- FIM DA NOVA IMPORTAÇÃO ---

load_dotenv()

app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(16))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///suporte.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode='eventlet')
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça login para acessar esta página."
login_manager.login_message_category = "warning"

# ... (As classes Usuario, Ticket, Mensagem e o comando create-db continuam exatamente iguais) ...
class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    def set_senha(self, senha): self.senha_hash = generate_password_hash(senha)
    def check_senha(self, senha): return check_password_hash(self.senha_hash, senha)

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
    anexo = db.Column(db.String(200), nullable=True)

class Mensagem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_protocolo = db.Column(db.String(20), db.ForeignKey('ticket.protocolo'), nullable=False)
    autor = db.Column(db.String(100), nullable=False)
    conteudo = db.Column(db.Text, nullable=False)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)
    is_system_message = db.Column(db.Boolean, default=False)

@app.cli.command('create-db')
def create_db():
    with app.app_context():
        db.create_all()
        print("Banco de dados criado.")
        if not Usuario.query.filter_by(email='jakelinesouza@hagmachado.com.br').first():
            admin = Usuario(nome='Jakeline Souza (Admin)', email='jakelinesouza@hagmachado.com.br', is_admin=True)
            admin.set_senha('Templo@25')
            db.session.add(admin)
            db.session.commit()
            print("Usuário administrador criado com sucesso.")

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# --- FUNÇÃO DE E-MAIL REESCRITA PARA SENDGRID ---
def enviar_email_notificacao(ticket, tipo='abertura'):
    SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
    EMAIL_REMETENTE = os.getenv('EMAIL_USER') # Usando o mesmo e-mail de antes como remetente

    if not SENDGRID_API_KEY or not EMAIL_REMETENTE:
        print("AVISO: Chave da API SendGrid ou e-mail do remetente não configurados.")
        return

    destinatarios = ['jakelinesouza@hagmachado.com.br', ticket.email_cliente]
    
    if tipo == 'abertura':
        assunto = f"Novo Ticket Aberto: {ticket.protocolo}"
        corpo_html = f"..." # O mesmo corpo HTML de antes
    else:
        assunto = f"Atualização no Ticket: {ticket.protocolo}"
        corpo_html = f"..." # O mesmo corpo HTML de antes

    for destinatario in destinatarios:
        message = Mail(
            from_email=EMAIL_REMETENTE,
            to_emails=destinatario,
            subject=assunto,
            html_content=corpo_html)
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            response = sg.send(message)
            print(f"E-mail enviado para {destinatario} via SendGrid. Status: {response.status_code}")
        except Exception as e:
            print(f"Falha ao enviar e-mail para {destinatario} via SendGrid: {e}")

# ... (O resto do código, rotas, etc., continua exatamente igual) ...
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        protocolo = f"TICKET-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        novo_ticket = Ticket(protocolo=protocolo, nome_cliente=request.form['nome'], email_cliente=request.form['email'], setor=request.form['setor'], funcao=request.form['funcao'], descricao=request.form['descricao'], status='Aguardando Resposta')
        db.session.add(novo_ticket)
        db.session.commit()
        enviar_email_notificacao(novo_ticket, tipo='abertura')
        return redirect(url_for('ticket_criado', protocolo=protocolo))
    return render_template('index.html')

# ... (todas as outras rotas) ...
@app.route('/ticket/<protocolo>/atualizar', methods=['POST'])
@login_required
def atualizar_ticket(protocolo):
    ticket = Ticket.query.filter_by(protocolo=protocolo).first_or_404()
    novo_status = request.form['novo_status']
    comentario = request.form.get('comentario')
    if ticket.status != novo_status:
        ticket.status = novo_status
        enviar_email_notificacao(ticket, tipo='atualizacao')
        msg_status = Mensagem(ticket_protocolo=protocolo, autor=current_user.nome, conteudo=f"Status alterado para: {novo_status}", is_system_message=True)
        db.session.add(msg_status)
    if comentario:
        msg_comentario = Mensagem(ticket_protocolo=protocolo, autor=current_user.nome, conteudo=f"Comentário interno: {comentario}", is_system_message=True)
        db.session.add(msg_comentario)
    db.session.commit()
    flash('Ticket atualizado com sucesso!', 'success')
    return redirect(url_for('ticket_detalhes', protocolo=protocolo))

# ... (o resto do código até o final) ...
@app.route('/chat/<protocolo>')
def chat(protocolo):
    ticket = Ticket.query.filter_by(protocolo=protocolo).first_or_404()
    historico = Mensagem.query.filter_by(ticket_protocolo=protocolo).order_by(Mensagem.data_envio).all()
    nome_usuario = current_user.nome if current_user.is_authenticated else ticket.nome_cliente
    session['nome_usuario'] = nome_usuario
    return render_template('chat.html', protocolo=protocolo, historico=historico, nome_usuario=nome_usuario)

@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    emit('message', {'msg': f'{username} entrou no chat.', 'username': 'Sistema', 'is_system': True}, to=room)

@socketio.on('message')
def handle_message(data):
    room = data['room']
    nova_mensagem = Mensagem(ticket_protocolo=room, autor=data['username'], conteudo=data['msg'])
    db.session.add(nova_mensagem)
    db.session.commit()
    emit('message', data, to=room)

if __name__ == '__main__':
    socketio.run(app, debug=True)



